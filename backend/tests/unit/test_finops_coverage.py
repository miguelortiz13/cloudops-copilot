"""
Pruebas de la cobertura parcial de costos en FinOpsService.

El Service Principal de la plataforma tiene lectura global sobre el tenant pero
el rol `Cost Management Reader` solo sobre algunas suscripciones. La regla que
se verifica aqui es la que evita el error mas caro del modulo: presentar como
"gasto real" un total que en realidad solo cubre una parte del scope.

Se usan dobles en lugar de llamar a Azure para que la prueba sea determinista y
no dependa de permisos ni de los limites de tasa de Cost Management.

Ejecutar con:

    ./.venv/bin/python3 tests/test_finops_coverage.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

from app.services.finops_service import FinOpsService  # noqa: E402

SUB_CUBIERTA = "11111111-1111-1111-1111-111111111111"
SUB_SIN_PERMISO = "22222222-2222-2222-2222-222222222222"

DISCO_MEDIDO = f"/subscriptions/{SUB_CUBIERTA}/resourcegroups/rg-a/providers/microsoft.compute/disks/disco-medido"
DISCO_NO_MEDIDO = f"/subscriptions/{SUB_SIN_PERMISO}/resourcegroups/rg-b/providers/microsoft.compute/disks/disco-estimado"


class AgenteFalso:
    """Devuelve respuestas fijas de Resource Graph segun la consulta."""

    azure_connected = True

    def query_azure_resource_graph(self, query, bypass_cache=False, subscriptions=None):
        if "microsoft.compute/disks" in query:
            return [
                {"id": DISCO_MEDIDO, "name": "disco-medido", "resourceGroup": "rg-a", "sizeGB": 100},
                {"id": DISCO_NO_MEDIDO, "name": "disco-estimado", "resourceGroup": "rg-b", "sizeGB": 200},
            ]
        if "microsoft.resources/subscriptions" in query:
            return [
                {"subscriptionId": SUB_CUBIERTA, "name": "Suscripcion Medida"},
                {"subscriptionId": SUB_SIN_PERMISO, "name": "Suscripcion Sin Costos"},
            ]
        if "project id, tags" in query:
            return [
                {"id": DISCO_MEDIDO, "tags": {"Customer": "Acme"}},
                {"id": DISCO_NO_MEDIDO, "tags": {}},
            ]
        return []


class CostServiceFalso:
    """Simula permisos de Cost Management sobre una sola suscripcion."""

    def get_cost_by_resource(self, subscription_ids, days=30):
        return {
            "status": "partial",
            "currency": "USD",
            "window_days": 30,
            # 30 USD en la ventana de 30 dias => 30 USD/mes.
            "costs": {DISCO_MEDIDO.lower(): 30.0},
            "coverage": {
                "covered": [SUB_CUBIERTA],
                "denied": [SUB_SIN_PERMISO],
                "failed": [],
            },
        }

    def costs_for(self, subscription_ids, allow_query=True):
        # El reporte entra por aqui: en el servicio real sirve primero de la
        # cache que dejo la precarga, sea cual sea el scope con que se guardo, y
        # solo consulta a Cost Management lo que ninguna entrada cubra.
        datos = self.get_cost_by_resource(subscription_ids)
        return {**datos, "source": "cache", "cache_age_seconds": 0}

    def get_daily_costs(self, subscription_ids, days=30):
        return {"status": "partial", "currency": "USD", "series": {},
                "coverage": {"covered": [SUB_CUBIERTA], "denied": [SUB_SIN_PERMISO], "failed": []}}

    def get_budgets(self, subscription_ids):
        return {"status": "partial", "budgets": [],
                "coverage": {"covered": [SUB_CUBIERTA], "denied": [SUB_SIN_PERMISO], "failed": []}}


class MetricsServiceFalso:
    def get_average_cpu(self, resource_ids, days=30):
        return {}


def construir_reporte():
    servicio = FinOpsService(AgenteFalso(), CostServiceFalso(), MetricsServiceFalso())
    return servicio.build_report([SUB_CUBIERTA, SUB_SIN_PERMISO])


def test_estado_es_parcial_no_exitoso():
    """Con una suscripcion medida y otra sin permisos, el estado no es 'success'."""
    cost_data = construir_reporte()["cost_data"]
    assert cost_data["status"] == "partial", cost_data["status"]
    assert cost_data["basis"] == "partial", cost_data["basis"]


def test_mensaje_declara_la_cobertura_y_el_motivo():
    """El mensaje dice a cuantas suscripciones alcanza y por que faltan las otras."""
    mensaje = construir_reporte()["cost_data"]["message"]
    assert "1 de 2 suscripciones" in mensaje, mensaje
    assert "Cost Management Reader" in mensaje, mensaje


def test_cobertura_enumera_ambos_lados():
    cobertura = construir_reporte()["cost_data"]["coverage"]
    assert cobertura["covered_count"] == 1
    assert cobertura["uncovered_count"] == 1
    assert cobertura["covered"][0]["name"] == "Suscripcion Medida"
    sin_costo = cobertura["uncovered"][0]
    assert sin_costo["name"] == "Suscripcion Sin Costos"
    assert sin_costo["reason"] == "sin_permisos"


def test_cost_basis_se_decide_por_recurso():
    """Cada disco se marca segun la suscripcion a la que pertenece."""
    discos = {d["name"]: d for d in construir_reporte()["unattached_disks"]}
    assert discos["disco-medido"]["cost_basis"] == "actual"
    assert discos["disco-estimado"]["cost_basis"] == "estimated"


def test_costo_real_y_estimado_no_se_confunden():
    """El disco medido usa la factura; el otro, el precio de referencia por GB."""
    reporte = construir_reporte()
    discos = {d["name"]: d for d in reporte["unattached_disks"]}
    # 30 USD facturados en 30 dias -> 30.0 USD/mes.
    assert discos["disco-medido"]["monthly_cost_usd"] == 30.0
    # 200 GB x 0.05 USD/GB -> 10.0 USD/mes estimados.
    assert discos["disco-estimado"]["monthly_cost_usd"] == 10.0

    ahorro = reporte["savings_lifecycle"]
    assert ahorro["potential_from_billing_usd"] == 30.0
    assert ahorro["potential_from_estimate_usd"] == 10.0
    assert ahorro["potential_savings_usd"] == 40.0


def test_showback_solo_atribuye_lo_facturado():
    """La atribucion por tag no inventa gasto de suscripciones sin medir."""
    reporte = construir_reporte()
    filas = reporte["insights"]["showback_chargeback"]
    assert reporte["insights"]["showback_status"] == "partial"
    por_customer = {f["value"]: f for f in filas if f["dimension"] == "Customer"}
    # Solo el recurso medido aporta gasto, y aparece bajo su tag Customer.
    assert por_customer["Acme"]["monthly_cost_usd"] == 30.0
    # El recurso sin medir no aparece como "Sin Customer" con costo inventado.
    assert "Sin Customer" not in por_customer


if __name__ == "__main__":
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for prueba in pruebas:
        try:
            prueba()
            print(f"  PASA  {prueba.__name__}")
        except AssertionError as exc:
            fallos += 1
            print(f"  FALLA {prueba.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            fallos += 1
            print(f"  ERROR {prueba.__name__}: {type(exc).__name__}: {exc}")

    print()
    print(f"{len(pruebas) - fallos}/{len(pruebas)} pruebas pasaron")
    sys.exit(1 if fallos else 0)

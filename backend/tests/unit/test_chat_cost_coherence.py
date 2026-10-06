"""
Pruebas de coherencia entre el costo que reporta el chat y el que reporta el panel.

El reporte de costo por grupo de recursos del agente sumaba estimaciones por SKU
y las publicaba en la clave `actual_cost_management` —el nombre del gasto
facturado—, con un pronostico calculado como el total x 1.2 y una tabla sembrada
con importes fijos para un grupo concreto. La misma pregunta daba una cifra en el
chat y otra en el panel, y ninguna de las dos decia cual era real.

Lo que se verifica aqui es que el chat toma el gasto facturado de la misma fuente
que el panel, aplica la misma regla por recurso, y nunca presenta una estimacion
sin marcarla como tal.

Se usan dobles en lugar de llamar a Azure para que la prueba sea determinista.

Ejecutar con:

    ./.venv/bin/python3 tests/test_chat_cost_coherence.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

from app.agents.azure_agent import AzureInventoryAgent  # noqa: E402
from app.services.finops_service import FinOpsService  # noqa: E402

SUB_MEDIDA = "11111111-1111-1111-1111-111111111111"
SUB_SIN_PERMISO = "22222222-2222-2222-2222-222222222222"
GRUPO = "rg-mixto"

DISCO_MEDIDO = (
    f"/subscriptions/{SUB_MEDIDA}/resourcegroups/{GRUPO}"
    "/providers/microsoft.compute/disks/disco-medido"
)
DISCO_NO_MEDIDO = (
    f"/subscriptions/{SUB_SIN_PERMISO}/resourcegroups/{GRUPO}"
    "/providers/microsoft.compute/disks/disco-estimado"
)

RECURSOS_DEL_GRUPO = [
    {
        "id": DISCO_MEDIDO,
        "name": "disco-medido",
        "type": "microsoft.compute/disks",
        "location": "eastus2",
        "tags": {},
        "sku": {"name": "Standard_LRS", "tier": "Standard"},
        # 512 GB en el catalogo de precios cuesta bastante mas que los 30 USD
        # que dice la factura: si el reporte devolviera la estimacion en vez del
        # gasto real, la diferencia saltaria a la vista.
        "properties": {"diskSizeGB": 512},
        "kind": "",
        "subscriptionId": SUB_MEDIDA,
    },
    {
        "id": DISCO_NO_MEDIDO,
        "name": "disco-estimado",
        "type": "microsoft.compute/disks",
        "location": "eastus2",
        "tags": {},
        "sku": {"name": "Standard_LRS", "tier": "Standard"},
        "properties": {"diskSizeGB": 128},
        "kind": "",
        "subscriptionId": SUB_SIN_PERMISO,
    },
]


class CostServiceFalso:
    """Simula permisos de Cost Management sobre una sola suscripcion."""

    def __init__(self, cubiertas=(SUB_MEDIDA,)):
        self.cubiertas = list(cubiertas)

    def get_cost_by_resource(self, subscription_ids, days=30, **kwargs):
        denegadas = [s for s in subscription_ids if s not in self.cubiertas]
        costos = {DISCO_MEDIDO.lower(): 30.0} if SUB_MEDIDA in self.cubiertas else {}
        return {
            "status": "partial" if denegadas and self.cubiertas else "unauthorized",
            "currency": "USD",
            "window_days": 30,
            "costs": costos,
            "coverage": {
                "covered": [s for s in subscription_ids if s in self.cubiertas],
                "denied": denegadas,
                "failed": [],
            },
        }

    def costs_for(self, subscription_ids, allow_query=True):
        # El chat entra por aqui: en el servicio real sirve primero de la cache
        # que dejo la precarga y solo consulta lo que falte.
        datos = self.get_cost_by_resource(subscription_ids)
        return {**datos, "source": "cache", "cache_age_seconds": 0}

    def get_daily_costs(self, subscription_ids, days=30, **kwargs):
        return {"status": "partial", "currency": "USD", "series": {},
                "coverage": {"covered": list(self.cubiertas), "denied": [], "failed": []}}

    def get_budgets(self, subscription_ids):
        return {"status": "partial", "budgets": [],
                "coverage": {"covered": list(self.cubiertas), "denied": [], "failed": []}}


class MetricsServiceFalso:
    def get_average_cpu(self, resource_ids, days=30):
        return {}


def agente_falso(cost_service=None):
    """
    Agente sin conexion: se omite __init__ a proposito.

    El constructor real se autentica contra Azure, y esta prueba tiene que
    correr sin credenciales y sin red.
    """
    agente = AzureInventoryAgent.__new__(AzureInventoryAgent)
    agente.azure_connected = True
    agente._cost = cost_service or CostServiceFalso()
    agente._secops = None
    agente._finops = None
    agente.query_azure_resource_graph = (
        lambda query, bypass_cache=False, subscriptions=None: (
            list(RECURSOS_DEL_GRUPO) if "resourcegroup =~" in query.lower() else []
        )
    )
    return agente


def reporte(cost_service=None):
    return agente_falso(cost_service).generate_rg_cost_report(GRUPO)


def por_nombre(rep):
    return {r["name"]: r for r in rep["top_expensive_resources"]}


def test_el_recurso_facturado_usa_la_factura_y_no_el_catalogo():
    """30 USD en 30 dias son 30 USD/mes, no lo que diga la tabla de precios."""
    disco = por_nombre(reporte())["disco-medido"]
    assert disco["cost_basis"] == "actual", disco["cost_basis"]
    assert disco["monthly_cost_usd"] == 30.0, disco["monthly_cost_usd"]


def test_el_recurso_sin_permisos_queda_marcado_como_estimado():
    disco = por_nombre(reporte())["disco-estimado"]
    assert disco["cost_basis"] == "estimated", disco["cost_basis"]
    assert disco["monthly_cost_usd"] > 0.0


def test_cobertura_parcial_separa_facturado_de_estimado():
    """Los dos totales viajan aparte: no se suma factura con estimacion a ciegas."""
    rep = reporte()
    assert rep["cost_basis"] == "partial", rep["cost_basis"]
    assert rep["billed_resources_count"] == 1
    assert rep["billed_monthly_cost_usd"] == 30.0
    assert rep["estimated_monthly_cost_usd"] > 0.0
    assert rep["total_monthly_cost_usd"] == round(
        rep["billed_monthly_cost_usd"] + rep["estimated_monthly_cost_usd"], 2
    )


def test_sin_ninguna_suscripcion_medida_nada_se_llama_facturado():
    rep = reporte(CostServiceFalso(cubiertas=()))
    assert rep["cost_basis"] == "estimated", rep["cost_basis"]
    assert rep["billed_monthly_cost_usd"] == 0.0
    assert rep["billed_resources_count"] == 0
    assert "estimación" in rep["coverage_note"]


def test_el_reporte_no_publica_pronostico_inventado():
    """El pronostico era el total x 1.2 cuando la API no respondia."""
    rep = reporte()
    assert "forecast_cost_management" not in rep
    assert not any("forecast" in clave for clave in rep)
    # Y la clave que nombraba gasto facturado ya no puede traer estimaciones.
    assert "actual_cost_management" not in rep


def test_el_chat_y_el_panel_dan_la_misma_cifra_del_mismo_recurso():
    """
    El disco medido cuesta lo mismo se pregunte donde se pregunte.

    Es la contradiccion que motivo el cambio: el panel leia la factura y el chat
    sumaba precios de catalogo.
    """
    del_chat = por_nombre(reporte())["disco-medido"]["monthly_cost_usd"]

    class AgenteParaFinOps:
        azure_connected = True

        def query_azure_resource_graph(self, query, bypass_cache=False, subscriptions=None):
            if "microsoft.compute/disks" in query:
                return [{"id": DISCO_MEDIDO, "name": "disco-medido",
                         "resourceGroup": GRUPO, "sizeGB": 512}]
            return []

    finops = FinOpsService(AgenteParaFinOps(), CostServiceFalso(), MetricsServiceFalso())
    panel = finops.build_report([SUB_MEDIDA, SUB_SIN_PERMISO])
    del_panel = {d["name"]: d for d in panel["unattached_disks"]}["disco-medido"]

    assert del_panel["cost_basis"] == "actual"
    assert del_chat == del_panel["monthly_cost_usd"], f"{del_chat} vs {del_panel['monthly_cost_usd']}"


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

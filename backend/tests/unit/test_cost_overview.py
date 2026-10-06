"""
Pruebas de la vista global de costos.

Fijan lo que el panel promete al mostrar la primera pantalla de FinOps:

- los totales salen de la serie diaria y comparan dos periodos iguales;
- la proyeccion de cierre de mes usa el promedio de los ultimos 7 dias;
- los desgloses suman el total, con "Otros" cuando hay demasiadas claves;
- un recurso facturado que ya no existe se muestra (su costo es real);
- los cargos que no pertenecen a ningun recurso se declaran aparte.

Ejecutar con:

    ./.venv/bin/python3 tests/unit/test_cost_overview.py
"""

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

from app.services.cost_overview_service import (  # noqa: E402
    CostOverviewService, _agrupar, resumir_serie, servicio_de, tipo_de,
)

SUB = "11111111-1111-1111-1111-111111111111"
BASE = f"/subscriptions/{SUB}/resourcegroups/rg-app/providers"
HOY = date(2026, 10, 15)


def serie_constante(valor_ultimos: float, valor_previos: float) -> dict:
    fin = HOY - timedelta(days=1)
    serie = {}
    for i in range(60):
        d = fin - timedelta(days=i)
        serie[d.isoformat()] = valor_ultimos if i < 30 else valor_previos
    return serie


class AgenteFalso:
    def __init__(self, recursos):
        self.recursos = recursos

    def query_azure_resource_graph(self, kql, bypass_cache=False, subscriptions=None):
        if "resourcecontainers" in kql:
            return [{"subscriptionId": SUB, "name": "Lab"}]
        return self.recursos


class CostosFalsos:
    def __init__(self, costos, serie):
        self.costos, self.serie = costos, serie

    def costs_for(self, subs, allow_query=True):
        return {"status": "success", "currency": "USD", "window_days": 30, "costs": self.costos,
                "coverage": {"covered": [SUB], "denied": [], "failed": []}}

    def get_daily_costs(self, subs, days=30, pace_seconds=0.0, force=False):
        return {"status": "success", "currency": "USD", "series": self.serie,
                "coverage": {"covered": [SUB], "denied": [], "failed": []}}


def test_totales_comparan_dos_periodos_iguales():
    r = resumir_serie(serie_constante(2.0, 1.0), HOY)
    assert r["last_period"] == 60.0
    assert r["previous_period"] == 30.0
    assert r["delta_percentage"] == 100.0
    assert r["daily_average"] == 2.0
    assert len(r["daily"]) == 60
    assert r["period_end"] == "2026-10-14"


def test_mes_en_curso_y_proyeccion_lineal():
    r = resumir_serie(serie_constante(2.0, 1.0), HOY)
    # Del 1 al 14 de octubre: 14 dias a 2.0.
    assert r["month_to_date"] == 28.0
    # Quedan 17 dias (15..31, sin facturar aun) al promedio de 7 dias (2.0).
    assert r["forecast_month"] == 28.0 + 2.0 * 17


def test_sin_periodo_previo_no_hay_delta():
    r = resumir_serie(serie_constante(2.0, 0.0), HOY)
    assert r["delta_percentage"] is None


def test_agrupar_suma_el_total_con_otros():
    filas = [(f"rg-{i}", 1.0) for i in range(20)]
    grupos = _agrupar(filas, 20.0, limite=5)
    assert len(grupos) == 5
    assert grupos[-1]["key"] == "Otros"
    assert sum(g["cost"] for g in grupos) == 20.0


def test_tipos_y_servicios_legibles():
    assert tipo_de(f"{BASE}/microsoft.storage/storageaccounts/st1") == "microsoft.storage/storageaccounts"
    assert tipo_de(f"{BASE}/microsoft.sql/servers/s1/databases/db1") == "microsoft.sql/servers/databases"
    assert servicio_de("microsoft.web/sites") == "App Service y Functions"
    assert servicio_de("microsoft.raro/cosas") == "cosas"


def test_vista_completa_con_recurso_borrado_y_cargos_sin_recurso():
    st = f"{BASE}/microsoft.storage/storageaccounts/st1"
    fn = f"{BASE}/microsoft.web/sites/func1"
    borrado = f"{BASE}/microsoft.containerservice/managedclusters/aks-viejo"
    recursos = [
        {"id": st, "name": "st1", "type": "microsoft.storage/storageaccounts",
         "resourceGroup": "rg-app", "location": "eastus2", "subscriptionId": SUB,
         "tags": {"Project": "sechub", "Environment": "prod"}},
        {"id": fn, "name": "func1", "type": "microsoft.web/sites",
         "resourceGroup": "rg-app", "location": "eastus2", "subscriptionId": SUB, "tags": {}},
    ]
    # 30 dias a 1.0 = 30 en la serie; los recursos suman 25 -> 5 sin recurso.
    servicio = CostOverviewService(
        AgenteFalso(recursos),
        CostosFalsos({st: 15.0, fn: 5.0, borrado: 5.0}, serie_constante(1.0, 1.0)),
    )
    vista = servicio.build([SUB], hoy=HOY)

    assert vista["basis"] == "actual"
    assert vista["totals"]["last_period"] == 30.0
    assert vista["totals"]["resource_attributed"] == 25.0
    assert vista["totals"]["unassigned_charges"] == 5.0
    assert vista["totals"]["deleted_resources_with_cost"] == 1

    top = vista["top_resources"]
    assert [r["name"] for r in top] == ["st1", "func1", "aks-viejo"]
    assert top[0]["share"] == 50.0
    assert top[2]["deleted"] is True
    assert top[2]["service"] == "Kubernetes Service (AKS)"

    # conftest fija el esquema de los fixtures; Environment es una de sus tags.
    ambientes = {g["key"]: g["cost"] for g in vista["by_tag"]["Environment"]}
    assert ambientes == {"prod": 15.0, "Sin Environment": 10.0}
    assert vista["by_subscription"][0]["key"] == "Lab"


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
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} pruebas pasaron")
    sys.exit(1 if fallos else 0)

"""
Pruebas de los routers con servicios sustituidos.

Los endpoints reciben sus servicios por `Depends` (app/core/deps.py), asi que
aqui se reemplaza el contenedor completo con dobles: se verifica el contrato
HTTP (rutas, parametros, codigos y forma de la respuesta) sin tocar Azure ni
construir el agente.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import deps  # noqa: E402
from app.main import app  # noqa: E402


class Registro:
    """Doble generico: guarda las llamadas y devuelve lo configurado."""

    def __init__(self, **respuestas):
        self.llamadas = []
        self._respuestas = respuestas

    def __getattr__(self, nombre):
        if nombre.startswith("_"):
            raise AttributeError(nombre)

        def metodo(*args, **kwargs):
            self.llamadas.append((nombre, args, kwargs))
            valor = self._respuestas[nombre]
            if isinstance(valor, Exception):
                raise valor
            return valor

        return metodo


@pytest.fixture
def servicios():
    s = SimpleNamespace(
        agent=Registro(),
        inventory=Registro(list_accessible_subscriptions=([{"subscriptionId": "s1"}], [])),
        history=Registro(record=None),
        cost=Registro(),
        metrics=Registro(),
        finops=Registro(),
        secops=Registro(build_report={"findings": [], "severity_summary": {}}),
        k8s=Registro(),
        risk=Registro(),
        tfstate=Registro(),
        cost_overview=Registro(build={"basis": "actual", "totals": {"last_period": 12.5}}),
    )
    s.agent.azure_connected = True
    s.inventory._cache_ttl = 300
    app.dependency_overrides[deps.services] = lambda: s
    yield s
    app.dependency_overrides.clear()


@pytest.fixture
def cliente(servicios):
    # Sin `with`: no se ejecuta el lifespan (ni la precarga de costos).
    return TestClient(app)


def test_costos_reparte_las_suscripciones_del_query(cliente, servicios):
    r = cliente.get("/api/finops/costs", params={"subscriptions": "a,b"})
    assert r.status_code == 200
    assert r.json()["totals"]["last_period"] == 12.5
    assert servicios.cost_overview.llamadas == [("build", (["a", "b"],), {})]


def test_costos_sin_scope_pide_todas(cliente, servicios):
    cliente.get("/api/finops/costs")
    assert servicios.cost_overview.llamadas == [("build", (None,), {})]


def test_error_del_servicio_se_traduce_en_500(cliente, servicios):
    servicios.cost_overview._respuestas["build"] = RuntimeError("Cost Management no responde")
    r = cliente.get("/api/finops/costs")
    assert r.status_code == 500
    assert "Cost Management no responde" in r.json()["detail"]


def test_suscripciones(cliente):
    r = cliente.get("/api/inventory/subscriptions")
    assert r.json() == {"subscriptions": [{"subscriptionId": "s1"}], "warnings": [], "total": 1}


def test_resumen_registra_el_punto_historico(cliente, servicios):
    resumen = {"totalResources": 3}
    servicios.inventory._respuestas["get_summary"] = resumen
    r = cliente.post("/api/inventory/summary", json={"subscriptionIds": ["s1"]})
    assert r.status_code == 200
    assert r.json() == resumen
    assert servicios.history.llamadas == [("record", (["s1"], resumen), {})]


def test_resumen_no_falla_si_el_historico_falla(cliente, servicios):
    servicios.inventory._respuestas["get_summary"] = {"totalResources": 3}
    servicios.history._respuestas["record"] = OSError("disco lleno")
    r = cliente.post("/api/inventory/summary", json={"subscriptionIds": []})
    assert r.status_code == 200


def test_health_refleja_la_conexion_del_agente(cliente, servicios):
    assert cliente.get("/api/inventory/health").json()["status"] == "ok"
    servicios.agent.azure_connected = False
    assert cliente.get("/api/inventory/health").json()["status"] == "degraded"


def test_reporte_de_seguridad_con_scope(cliente, servicios):
    r = cliente.get("/api/secops/report", params={"subscriptions": "s1"})
    assert r.status_code == 200
    assert servicios.secops.llamadas == [("build_report", (["s1"],), {})]

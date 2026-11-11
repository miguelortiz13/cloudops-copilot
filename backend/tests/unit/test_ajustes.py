"""
Plataforma → Ajustes (fase 2 del plan 10): registro por dominio, origen, historial y deshacer,
y las reglas que antes eran variables de entorno.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import ajustes, config, deps  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def cliente():
    app.dependency_overrides[deps.services] = lambda: SimpleNamespace(azure=SimpleNamespace(azure_credentials=None))
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_las_reglas_de_variables_de_entorno_son_el_valor_inicial_hasta_guardarlas(monkeypatch):
    monkeypatch.setenv("MONTHLY_BUDGETS_USD", "azure=5,aws=2.5")
    assert ajustes.presupuestos() == {"azure": 5.0, "aws": 2.5} and ajustes.origen("costos") == "variable"
    ajustes.guardar("costos", {"presupuesto_aws_usd": 0}, "ana@x")
    assert ajustes.presupuestos() == {"azure": 5.0} and ajustes.origen("costos") == "ajuste"

    ajustes.guardar("gobierno", {"tags_obligatorias": [" Owner ", "Env", "Owner"]}, "ana@x")
    assert config.MANDATORY_TAGS == ["Owner", "Env"]  # el resto del código lee config: se actualiza en su lugar
    ajustes.guardar("ia", {"max_consultas_hora": 10}, "ana@x")
    assert config.LLM_MAX_REQUESTS_PER_HOUR == 10


@pytest.mark.parametrize("seccion,cambio", [
    ("gobierno", {"tags_obligatorias": []}), ("gobierno", {"tags_obligatorias": ["a/b"]}),
    ("costos", {"presupuesto_azure_usd": -1}), ("costos", {"presupuesto_azure_usd": "5"}),
    ("ia", {"max_consultas_dia": 1.5}), ("incidentes", {"inventado": 1}),
])
def test_valida_tipos_y_rangos(seccion, cambio):
    with pytest.raises(ValueError):
        ajustes.guardar(seccion, cambio)


def test_historial_y_deshacer():
    ajustes.guardar("incidentes", {"umbral_tormenta": 5}, "ana@x")
    ajustes.guardar_cluster("lab", {"reinicios": 9}, "bob@x")
    h = ajustes.historial()
    assert [(e["seccion"], e["actor"]) for e in h] == [("cluster:lab", "bob@x"), ("incidentes", "ana@x")]
    assert h[1]["antes"]["umbral_tormenta"] == 3 and h[1]["despues"]["umbral_tormenta"] == 5
    ajustes.deshacer(1, "ana@x")
    assert ajustes.incidentes()["umbral_tormenta"] == 3 and ajustes.historial()[0]["actor"] == "ana@x"
    ajustes.deshacer(1, "ana@x")  # ahora el de Kubernetes
    assert ajustes.cluster("lab")["reinicios"] == 5
    with pytest.raises(ValueError):
        ajustes.deshacer(99, "ana@x")


def test_api_de_ajustes(cliente):
    todo = cliente.get("/api/settings").json()["sections"]
    assert set(todo) == {"incidentes", "gobierno", "costos", "ia", "avisos", "riesgo", "chequeos", "asignacion"} and todo["gobierno"]["origin"] == "variable"
    assert todo["costos"]["schema"]["presupuesto_aws_usd"] == ["float", 0, 1_000_000]
    assert cliente.put("/api/settings/costos", json={"presupuesto_azure_usd": -3}).status_code == 400
    assert cliente.put("/api/settings/nada", json={}).status_code == 404
    r = cliente.put("/api/settings/costos", json={"presupuesto_azure_usd": 12.5}).json()
    assert r["values"]["presupuesto_azure_usd"] == 12.5 and r["origin"] == "ajuste"
    # La ruta anterior de incidentes sigue respondiendo (no la tapa la genérica).
    assert cliente.put("/api/settings/incidents", json={"foto_vieja_min": 30}).json()["values"]["foto_vieja_min"] == 30
    h = cliente.get("/api/settings-history").json()["items"]
    assert [e["seccion"] for e in h] == ["incidentes", "costos"]
    assert cliente.post("/api/settings-history/1/undo").json()["values"]["presupuesto_azure_usd"] == 0.0
    assert cliente.post("/api/settings-history/50/undo").status_code == 404


def test_el_navegador_puede_guardar_ajustes_y_quitar_silencios(cliente):
    """Preflight CORS de PUT y DELETE desde el panel (otro origen): antes solo se permitían GET y POST."""
    origen = config.ALLOWED_ORIGINS[0] if config.ALLOWED_ORIGINS else "http://localhost:5173"
    for metodo in ("PUT", "DELETE"):
        r = cliente.options("/api/settings/costos", headers={"Origin": origen, "Access-Control-Request-Method": metodo})
        assert r.status_code == 200 and metodo in r.headers["access-control-allow-methods"]

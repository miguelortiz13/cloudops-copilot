"""
Trazas de IA (plan 11, hito IA-1): una por ejecución con spans de modelo y herramientas, sin guardar el texto,
y el resumen de Plataforma → IA con costo estimado y latencia.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import llm  # noqa: E402
from app.ai import agente  # noqa: E402
from app.ai.agente import Herramienta  # noqa: E402
from app.core import ajustes, config, deps, trazas  # noqa: E402
from app.llm.base import Llamada, Paso, Respuesta  # noqa: E402
from app.main import app  # noqa: E402

PREGUNTA = "¿Cuál es el secreto del cliente Contoso?"


class Modelo:
    nombre, modelo = "falso", "falso-1"

    def __init__(self):
        self.turnos = [Paso(texto=None, llamadas=[Llamada("contar", {"severidad": "critica"}), Llamada("rota", {})],
                            tokens_entrada=1000, tokens_salida=50),
                       Paso(texto="Hay 3 críticos.", tokens_entrada=1500, tokens_salida=100)]

    def iniciar(self, mensaje):
        return []

    def paso(self, sistema, historial, decls):
        return self.turnos.pop(0)

    def agregar_resultados(self, historial, resultados):
        pass

    def generar(self, sistema, mensaje, **k):
        return Respuesta(texto="**Resumen** listo", modelo="falso-1", tokens_entrada=400, tokens_salida=80)


@pytest.fixture(autouse=True)
def datos(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    llm.reiniciar(Modelo())
    yield
    llm.reiniciar(None)


HERRAMIENTAS = [Herramienta("contar", "x", {"type": "object", "properties": {"severidad": {"type": "string"}}}, lambda severidad: {"total": 3}),
                Herramienta("rota", "x", {"type": "object", "properties": {}}, lambda: 1 / 0)]


def test_una_traza_por_ejecucion_con_spans_y_sin_el_texto():
    r = agente.responder("sistema", PREGUNTA, HERRAMIENTAS, uso="incidente.diagnostico", usuario="ana@x")
    llm.generar("costos.explicar", "s", PREGUNTA, usuario="bob@x")
    t = next(x for x in trazas.leer(1) if x["trace_id"] == r["trace_id"])
    a = t["attributes"]
    assert (t["name"], a["cloudops.domain"], a["gen_ai.usage.input_tokens"], a["gen_ai.usage.output_tokens"]) == (
        "invoke_agent incidente.diagnostico", "operacion", 2500, 150)
    assert [s["name"] for s in t["spans"]] == ["chat falso-1", "execute_tool contar", "execute_tool rota", "chat falso-1"]
    assert t["spans"][2]["attributes"]["error.type"].startswith("ZeroDivisionError")
    assert t["spans"][1]["attributes"]["cloudops.tool.arguments"] == {"severidad": "critica"}
    # Ni la pregunta ni la respuesta se guardan: solo su tamaño.
    contenido = "".join(p.read_text() for p in (config.DATA_DIR / "trazas").iterdir())
    assert "Contoso" not in contenido and "Hay 3 críticos" not in contenido and a["cloudops.response_chars"] == len("Hay 3 críticos.")
    directa = next(x for x in trazas.leer(1) if x["name"] == "chat costos.explicar")
    assert directa["attributes"]["cloudops.domain"] == "costos" and directa["attributes"]["gen_ai.usage.input_tokens"] == 400


def test_resumen_con_costo_estimado_y_api():
    agente.responder("s", PREGUNTA, HERRAMIENTAS, uso="asistente.chat")
    llm.generar("costos.explicar", "s", "x")
    sin_precio = trazas.resumen(trazas.leer(1), 0, 0)
    assert sin_precio["priced"] is False and sin_precio["total"]["calls"] == 2
    ajustes.guardar("ia", {"precio_entrada_usd_1m": 0.5, "precio_salida_usd_1m": 2.0})
    app.dependency_overrides[deps.services] = lambda: SimpleNamespace(azure=None)
    try:
        c = TestClient(app)
        r = c.get("/api/ia/resumen?dias=1").json()
        # (2500 + 400) tokens de entrada a 0,50 y (150 + 80) de salida a 2,00 por millón.
        assert r["total"]["cost_usd"] == round((2900 * 0.5 + 230 * 2.0) / 1_000_000, 4) and r["priced"]
        assert set(r["by_domain"]) == {"inicio", "costos"} and r["tools"][0] == {"name": "contar", "calls": 1, "errors": 0}
        lista = c.get("/api/ia/trazas?uso=asistente.chat").json()
        assert lista["total"] == 1 and lista["items"][0]["spans"] == 4
        assert c.get(f"/api/ia/trazas/{lista['items'][0]['trace_id']}").json()["spans"][1]["name"] == "execute_tool contar"
        assert c.get("/api/ia/trazas/nada").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_ingesta_y_lectura_de_evals(monkeypatch):
    app.dependency_overrides[deps.services] = lambda: SimpleNamespace(azure=None)
    try:
        c = TestClient(app)
        corrida = {"model": "gemini-3.5-flash", "run": "123", "suites": [
            {"suite": "dominios", "cases": 5, "passed": 5, "accuracy": 1.0, "target": 0.9, "invented_numbers": 0, "details": []}]}
        monkeypatch.delenv("ALERTS_INGEST_TOKEN", raising=False)
        assert c.post("/api/ia/evals/ingesta", json=corrida).status_code == 503
        monkeypatch.setenv("ALERTS_INGEST_TOKEN", "t0k3n")
        assert c.post("/api/ia/evals/ingesta", json=corrida, headers={"Authorization": "Bearer otro"}).status_code == 401
        ok = {"Authorization": "Bearer t0k3n"}
        assert c.post("/api/ia/evals/ingesta", json={"nada": 1}, headers=ok).status_code == 400
        assert c.post("/api/ia/evals/ingesta", json=corrida, headers=ok).json() == {"stored": 1}
        runs = c.get("/api/ia/evals").json()["runs"]
        assert runs[0]["run"] == "123" and runs[0]["suites"][0]["accuracy"] == 1.0
    finally:
        app.dependency_overrides.clear()

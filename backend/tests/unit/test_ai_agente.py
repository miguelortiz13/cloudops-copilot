"""
Motor de agentes con herramientas (app/ai, plan 09 etapa A): el bucle, sus topes
y las herramientas sobre datos de prueba, con un modelo simulado.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402

from app import llm  # noqa: E402
from app.ai import agente, herramientas  # noqa: E402
from app.ai.agente import Herramienta  # noqa: E402
from app.llm.base import Llamada, LLMError, Paso  # noqa: E402


class Guion:
    """Modelo simulado: cada turno sale de una lista; guarda lo que recibió."""

    nombre, modelo = "falso", "falso-1"

    def __init__(self, *turnos):
        self.turnos, self.vistos = list(turnos), []

    def generar(self, *a, **k):
        raise AssertionError("el motor no usa generar()")

    def iniciar(self, mensaje):
        return [("usuario", mensaje)]

    def paso(self, sistema, historial, decls):
        self.vistos.append({"herramientas": [d["nombre"] for d in decls], "historial": list(historial)})
        turno = self.turnos.pop(0)
        if isinstance(turno, Exception):
            raise turno
        historial.append(("modelo", turno))
        return turno

    def agregar_resultados(self, historial, resultados):
        historial.append(("resultados", [(ll.nombre, dato) for ll, dato in resultados]))


@pytest.fixture(autouse=True)
def sin_modelo():
    yield
    llm.reiniciar(None)


def contar(severidad):
    return {"total": {"critica": 3}.get(severidad, 0), "enlace": "#/secops/gestion"}


HERRAMIENTAS = [
    Herramienta("contar", "Cuenta hallazgos.", {"type": "object", "properties": {"severidad": {"type": "string"}}}, contar),
    Herramienta("rota", "Siempre falla.", {"type": "object", "properties": {}}, lambda: 1 / 0),
]


def test_el_agente_llama_herramientas_y_responde_con_su_resultado():
    guion = Guion(Paso(texto=None, llamadas=[Llamada("contar", {"severidad": "critica"})], tokens_entrada=10),
                  Paso(texto="Hay 3 [ver](#/secops/gestion)", tokens_entrada=20, tokens_salida=5))
    llm.reiniciar(guion)
    r = agente.responder("sistema", "¿cuántos críticos?", HERRAMIENTAS, uso="prueba")
    assert r["answer"] == "Hay 3 [ver](#/secops/gestion)"
    assert r["tools"] == [{"nombre": "contar", "argumentos": {"severidad": "critica"}}]
    assert r["tokens"] == {"entrada": 30, "salida": 5}
    # El segundo turno recibió el resultado de la herramienta.
    assert ("resultados", [("contar", {"total": 3, "enlace": "#/secops/gestion"})]) in guion.vistos[1]["historial"]


def test_herramienta_que_falla_o_desconocida_o_con_argumentos_malos_no_corta_el_bucle():
    guion = Guion(Paso(texto=None, llamadas=[Llamada("rota", {}), Llamada("inventada", {}), Llamada("contar", {"x": 1})]),
                  Paso(texto="No pude obtener el dato."))
    llm.reiniciar(guion)
    r = agente.responder("s", "?", HERRAMIENTAS, uso="prueba")
    errores = [t["error"] for t in r["tools"]]
    assert errores[0].startswith("ZeroDivisionError") and errores[1] == "Herramienta desconocida."
    assert errores[2].startswith("Argumentos inválidos") and r["answer"] == "No pude obtener el dato."


def test_al_llegar_al_tope_se_pide_la_respuesta_sin_herramientas():
    pedir = Paso(texto=None, llamadas=[Llamada("contar", {"severidad": "alta"})])
    guion = Guion(pedir, pedir, Paso(texto="Con lo que tengo: 0 altas."))
    llm.reiniciar(guion)
    r = agente.responder("s", "?", HERRAMIENTAS, uso="prueba", max_llamadas=2)
    assert len(r["tools"]) == 2 and guion.vistos[2]["herramientas"] == []


def test_sin_soporte_de_herramientas_o_con_falla_del_modelo_sale_llm_error():
    class SoloTexto:
        nombre, modelo = "texto", "t"

    llm.reiniciar(SoloTexto())
    with pytest.raises(LLMError):
        agente.responder("s", "?", HERRAMIENTAS, uso="prueba")
    llm.reiniciar(Guion(LLMError("caído")))
    with pytest.raises(LLMError):
        agente.responder("s", "?", HERRAMIENTAS, uso="prueba")


def test_resultado_enorme_se_rechaza_con_un_error_util():
    grande = Herramienta("grande", "x", {"type": "object", "properties": {}}, lambda: {"x": "a" * 50_000})
    llm.reiniciar(Guion(Paso(texto=None, llamadas=[Llamada("grande", {})]), Paso(texto="ok")))
    assert "demasiado grande" in agente.responder("s", "?", [grande], uso="prueba")["tools"][0]["error"]


# ---------------------------------------------------------------- herramientas sobre datos

AHORA = datetime.now(timezone.utc)
RECURSOS = [
    {"uid": "azure:sub/1/st1", "name": "st-datos", "provider": "azure", "account": "lab", "type": "storage.account",
     "native_type": "microsoft.storage/storageaccounts", "cost_30d": 4.5, "in_iac": False, "created_by": "ana@x",
     "first_seen": (AHORA - timedelta(days=2)).isoformat(), "region": "eastus2", "group": "rg"},
    {"uid": "aws:account/1/b1", "name": "bucket-logs", "provider": "aws", "account": "prod", "type": "storage.bucket",
     "native_type": "s3:bucket", "cost_30d": 1.0, "in_iac": True, "created_by": None,
     "first_seen": (AHORA - timedelta(days=30)).isoformat(), "region": "us-east-1", "group": None},
]
HALLAZGOS = [
    {"account_uid": "azure:sub/1", "rule_id": "storage.public-blob-access", "title": "Blobs públicos", "severity": "alta",
     "status": "abierto", "resource_name": "st-datos", "account": "lab", "remediation": "Desactivar", "accepted_until": None,
     "first_seen": "2026-10-01"},
    {"account_uid": "aws:account/1", "rule_id": "aws.identity.root-without-mfa", "title": "Root sin MFA",
     "severity": "critica", "status": "resuelto", "resource_name": "root", "account": "prod", "remediation": "MFA",
     "accepted_until": None, "first_seen": "2026-10-02"},
]


@pytest.fixture
def datos(monkeypatch):
    from app.readmodel import service
    monkeypatch.setattr(service, "inventario_multinube", lambda: {"resources": RECURSOS})
    monkeypatch.setattr(service, "hallazgos", lambda: {"items": HALLAZGOS})


def test_buscar_recursos_filtra_y_acota(datos):
    r = herramientas.buscar_recursos(nube="azure", en_terraform=False)
    assert [x["name"] for x in r["muestra"]] == ["st-datos"] and r["enlace"] == "#/inventario"
    r = herramientas.buscar_recursos(tipo="storage", limite=1)
    assert (r["total"], r["truncado"], r["muestra"][0]["name"], r["gasto_30d_de_los_encontrados"]) == (2, True, "st-datos", 5.5)


def test_recursos_nuevos_y_hallazgos(datos):
    r = herramientas.recursos_nuevos(dias=7, solo_fuera_de_terraform=True)
    assert [(x["name"], x["created_by"]) for x in r["muestra"]] == [("st-datos", "ana@x")]
    assert herramientas.hallazgos()["por_severidad"] == {"alta": 1}  # el resuelto no es activo
    assert herramientas.hallazgos(estado="todos", nube="aws")["muestra"][0]["title"] == "Root sin MFA"


def test_herramientas_del_asistente_declaran_esquemas_validos():
    hs = herramientas.para_asistente(None)
    assert len({h.nombre for h in hs}) == len(hs) == 7
    for h in hs:
        assert h.parametros["type"] == "object" and h.descripcion


def test_ruta_del_chat_usa_el_motor_y_cae_al_agente_anterior_si_falla(monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from app.ai import asistente
    from app.core import deps
    from app.main import app

    anterior = SimpleNamespace(ask=lambda *a, **k: {"answer": "reglas", "mode": "reglas", "data": []})
    app.dependency_overrides[deps.services] = lambda: SimpleNamespace(agent=anterior, azure=SimpleNamespace(azure_credentials=None))
    try:
        llm.reiniciar(Guion())
        monkeypatch.setattr(asistente, "responder", lambda *a, **k: {"answer": "con herramientas", "tools": [{"nombre": "x", "argumentos": {}}]})
        r = TestClient(app).post("/api/chat", json={"message": "hola"}).json()
        assert (r["answer"], r["mode"], r["data"]) == ("con herramientas", "llm_falso_herramientas", [{"nombre": "x", "argumentos": {}}])

        def falla(*a, **k):
            raise LLMError("caído")

        monkeypatch.setattr(asistente, "responder", falla)
        assert TestClient(app).post("/api/chat", json={"message": "hola"}).json()["answer"] == "reglas"
    finally:
        app.dependency_overrides.clear()


def test_estado_cluster_enfoca_por_namespace_y_objeto():
    ahora = datetime.now(timezone.utc).isoformat()
    foto = {"collected_at": ahora, "nodes": [], "workloads": [], "services": [],
            "pods": [{"namespace": "boutique", "name": "currencyservice-abc-1", "phase": "Pending", "reason": "ImagePullBackOff",
                      "ready": 0, "containers": 1, "restarts": 0, "owner": "currencyservice-abc", "created": ahora}],
            # El evento del problema queda detrás de 150 de ruido de otro namespace.
            "events": [{"namespace": "monitoring", "name": f"x{n}", "reason": "Unhealthy", "message": "ruido", "last": ahora}
                       for n in range(150)]
                      + [{"namespace": "boutique", "name": "currencyservice-abc-1", "reason": "Failed",
                          "message": "Failed to pull image ...:v9.9.9: not found", "last": ahora}]}
    d = {"name": "lab", "incident_list": [], "problem_pods": foto["pods"], "workload_list": [], "node_list": [], "events": foto["events"][:50]}
    r = herramientas.enfocar(foto, d, "boutique", "currencyservice")
    assert [e["reason"] for e in r["eventos"]["muestra"]] == ["Failed"] and r["pods_con_problemas"]["total"] == 1
    sin = herramientas.enfocar(foto, d, None, None)
    assert sin["eventos"]["total"] == 151 and len(sin["eventos"]["muestra"]) == herramientas.MAX_EVENTOS

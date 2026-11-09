"""Base de conocimiento (plan 11, hito IA-4): corpus, índice incremental y búsqueda híbrida."""

import hashlib
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.ai import conocimiento, herramientas  # noqa: E402
from app.core import config, deps  # noqa: E402
from app.db import engine as db  # noqa: E402
from app.db.models import Base, ControlException, Incident, IncidentEvent  # noqa: E402

AHORA = datetime.now(timezone.utc)


class Embebedor:
    """Vectores de palabras con hash: parecidos si comparten palabras. Cuenta los textos que recibe."""

    def __init__(self):
        self.textos = 0

    def __call__(self, textos, consulta):
        self.textos += len(textos)
        salida = []
        for t in textos:
            v = [0.0] * 64
            for p in conocimiento._palabras(t):
                v[int(hashlib.md5(p.encode()).hexdigest(), 16) % 64] += 1
            n = math.sqrt(sum(x * x for x in v)) or 1
            salida.append([x / n for x in v])
        return salida


@pytest.fixture(autouse=True)
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'c.db'}")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conocimiento._cache.update({"mtime": None, "indice": None, "sin_indice": None, "hasta": 0.0})
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    inc = lambda id_, feedback, cierre, titulo: Incident(  # noqa: E731
        id=id_, key=f"k{id_}", source="alertmanager", cluster="lab", title=titulo, severity="alta", status="resuelto",
        alerts=[{"name": "KubePodCrashLooping", "summary": "Pod is crash looping."}], opened_at=AHORA - timedelta(days=3),
        last_alert_at=AHORA, resolved_at=AHORA, diagnosis=f"Causa probable: {titulo}", feedback=feedback, closed_reason=cierre)
    with db.session_scope() as s:
        s.add_all([inc(1, "correcto", None, "cartservice sin conexión a redis-cart"),
                   inc(2, "incorrecto", "solucionado", "diagnóstico equivocado"),
                   inc(3, None, "solucionado", "imagen paymentservice v9.9.9 inexistente")])
        s.add(IncidentEvent(incident_id=1, at=AHORA, actor="ana@x", kind="nota", text="Se reinició redis-cart y volvió."))
        s.add(ControlException(framework="cis-azure-2.0.0", control="8.7", justification="Key Vault de laboratorio sin datos reales",
                               created_by="ana@x", created_at=AHORA, until=AHORA.date() + timedelta(days=60)))
    yield
    db.reset_engine()


def test_el_corpus_trae_runbooks_guia_controles_incidentes_y_excepciones():
    chunks = conocimiento.corpus()
    tipos = {c["tipo"] for c in chunks}
    assert tipos == {"runbook", "guia", "control", "incidente", "excepcion"}
    titulos = [c["titulo"] for c in chunks]
    assert "Runbook: pod en CrashLoopBackOff · Diagnóstico" in titulos
    incidentes = {c["fuente"]: c for c in chunks if c["tipo"] == "incidente"}
    assert set(incidentes) == {"incidente/1", "incidente/3"}  # el marcado como incorrecto no entra
    assert "Se reinició redis-cart" in incidentes["incidente/1"]["texto"] and incidentes["incidente/1"]["enlace"] == "#/operacion/incidentes/1"
    assert all(len(c["texto"]) <= conocimiento.MAX_FRAGMENTO for c in chunks)


def test_sin_modelo_la_busqueda_es_lexica_y_encuentra_el_runbook():
    r = conocimiento.buscar("pod reiniciando, log dice connection refused a redis", embeber=None)
    assert r["modo"] == "léxico"
    fuentes = [x["fuente"] for x in r["resultados"]]
    assert any(f.startswith("conocimiento/runbooks/k8s-crashloopbackoff.md") for f in fuentes[:3])
    assert "incidente/1" in fuentes  # el incidente parecido ya resuelto
    assert conocimiento.buscar("ImagePullBackOff", tipo="runbook")["resultados"][0]["fuente"].startswith("conocimiento/runbooks/k8s-imagepullbackoff")


def test_reindexar_solo_genera_vectores_de_lo_que_cambio(monkeypatch):
    e = Embebedor()
    r = conocimiento.reindexar(e)
    assert r["indexado"] and r["con_vector"] == r["fragmentos"] == e.textos and r["nuevos"] == r["fragmentos"]
    antes = e.textos
    r = conocimiento.reindexar(e)
    assert e.textos == antes and r["nuevos"] == 0  # nada cambió: ningún vector nuevo
    with db.session_scope() as s:
        s.get(Incident, 3).postmortem = "Se publicó la imagen que faltaba."
    assert conocimiento.reindexar(e)["nuevos"] == 1 and e.textos == antes + 1
    monkeypatch.setattr(config, "GEMINI_EMBEDDING_MODEL", "otro-modelo")
    assert conocimiento.reindexar(e)["nuevos"] == r["fragmentos"]  # otro modelo: vectores nuevos para todo


def test_busqueda_hibrida_y_falla_del_modelo_cae_a_lexica():
    e = Embebedor()
    conocimiento.reindexar(e)
    r = conocimiento.buscar("cómo silencio una alerta del clúster", embeber=e)
    assert r["modo"] == "híbrido" and r["resultados"][0]["fuente"].startswith("conocimiento/guia/")

    def rota(textos, consulta):
        raise RuntimeError("sin cuota")
    assert conocimiento.buscar("silenciar alerta", embeber=rota)["modo"] == "léxico"


def test_la_herramienta_del_agente_y_las_rutas():
    h = {x.nombre: x for x in herramientas.para_asistente(None)}["buscar_conocimiento"]
    r = h.funcion(consulta="nodo NotReady tormenta", tipo="runbook")
    assert r["resultados"][0]["fuente"].startswith("conocimiento/runbooks/k8s-nodo-notready") and "Cita" in r["nota"]
    from app.main import app
    app.dependency_overrides[deps.services] = lambda: SimpleNamespace(azure=SimpleNamespace(azure_credentials=None))
    try:
        c = TestClient(app)
        assert c.get("/api/ia/conocimiento").json() == {"indexado": False}
        assert c.post("/api/ia/conocimiento/reindexar").status_code == 202
        estado = c.get("/api/ia/conocimiento").json()  # la tarea en segundo plano corre al terminar la respuesta
        assert estado["indexado"] and estado["por_tipo"]["runbook"] > 20 and estado["con_vector"] == 0
        assert c.get("/api/ia/conocimiento/buscar", params={"q": "excepción Key Vault"}).json()["resultados"]
    finally:
        app.dependency_overrides.clear()

"""
Incidentes (plan 09, etapa B): de la alerta de Alertmanager al diagnóstico y su
reporte, con base SQLite y un modelo simulado.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import llm  # noqa: E402
from app.ai import incidentes  # noqa: E402
from app.core import config, deps  # noqa: E402
from app.db import engine as db  # noqa: E402
from app.db.models import Base, Incident  # noqa: E402
from app.llm import limits  # noqa: E402
from app.llm.base import Llamada, Paso  # noqa: E402
from app.main import app  # noqa: E402

AHORA = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def webhook(status="firing", grupo="{}:{alertname=\"KubePodCrashLooping\"}", alertas=None):
    alertas = alertas if alertas is not None else [{
        "status": status, "startsAt": "2026-10-30T11:50:00Z", "endsAt": "0001-01-01T00:00:00Z",
        "labels": {"alertname": "KubePodCrashLooping", "namespace": "boutique", "pod": "paymentservice-1",
                   "severity": "warning"},
        "annotations": {"summary": "Pod is crash looping.", "description": "Pod boutique/paymentservice-1 is in waiting state"}}]
    return {"version": "4", "status": status, "groupKey": grupo, "alerts": alertas,
            "commonLabels": {"alertname": "KubePodCrashLooping", "namespace": "boutique"}}


@pytest.fixture(autouse=True)
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'i.db'}")
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    limits.reiniciar()
    yield
    db.reset_engine()
    llm.reiniciar(None)
    limits.reiniciar()


def incidente(i):
    with db.session_scope() as s:
        x = s.get(Incident, i)
        return SimpleNamespace(**{c: getattr(x, c) for c in ("status", "severity", "title", "alerts", "diagnosis",
                                                            "diagnosis_status", "diagnosis_tools", "resolved_at")})


def test_un_grupo_es_un_incidente_y_se_cierra_al_resolverse():
    i, accion = incidentes.ingresar_alertmanager(webhook(), "local-k8s-lab", AHORA)
    assert accion == "nuevo"
    x = incidente(i)
    assert (x.status, x.severity, x.title) == ("abierto", "alta", "KubePodCrashLooping · boutique · paymentservice-1")
    # La misma alerta repetida (Alertmanager reenvía) no abre otro incidente.
    assert incidentes.ingresar_alertmanager(webhook(), "local-k8s-lab", AHORA + timedelta(minutes=5)) == (i, "actualizado")
    assert incidentes.ingresar_alertmanager(webhook("resolved"), "local-k8s-lab", AHORA + timedelta(minutes=20)) == (i, "resuelto")
    assert incidente(i).status == "resuelto"
    assert incidentes.ingresar_alertmanager(webhook("resolved"), "local-k8s-lab", AHORA) == (None, "ignorado")
    # Si vuelve a dispararse después de resuelto, es un incidente nuevo.
    nuevo, accion = incidentes.ingresar_alertmanager(webhook(), "local-k8s-lab", AHORA + timedelta(hours=1))
    assert accion == "nuevo" and nuevo != i


def test_severidad_sube_con_una_alerta_critica_del_mismo_grupo():
    i, _ = incidentes.ingresar_alertmanager(webhook(), "lab", AHORA)
    critica = webhook()
    critica["alerts"].append({"status": "firing", "labels": {"alertname": "KubeNodeNotReady", "severity": "critical"},
                              "annotations": {"summary": "Nodo caído"}})
    incidentes.ingresar_alertmanager(critica, "lab", AHORA)
    x = incidente(i)
    assert x.severity == "critica" and {a["name"] for a in x.alerts} == {"KubePodCrashLooping", "KubeNodeNotReady"}


def test_webhook_invalido():
    with pytest.raises(incidentes.AlertaInvalida):
        incidentes.ingresar_alertmanager({"alerts": []}, None)


class Guion:
    nombre, modelo = "falso", "f"

    def __init__(self, *turnos):
        self.turnos = list(turnos)

    def iniciar(self, mensaje):
        self.mensaje = mensaje
        return []

    def paso(self, sistema, historial, decls):
        self.sistema = sistema
        return self.turnos.pop(0)

    def agregar_resultados(self, historial, resultados):
        pass


@pytest.fixture
def canal(monkeypatch):
    from app.collectors import notify
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://discord.com/api/webhooks/1/SECRETO")
    monkeypatch.setattr(config, "FRONTEND_URL", "https://panel.example")
    enviados = []
    monkeypatch.setattr(notify.requests, "post", lambda url, json=None, timeout=None: enviados.append(json) or SimpleNamespace(status_code=204))
    return enviados


def test_diagnostico_con_herramientas_se_guarda_y_se_publica(canal, monkeypatch):
    from app.ai import herramientas
    monkeypatch.setattr(herramientas, "para_asistente", lambda cred: [
        herramientas.Herramienta("estado_cluster", "x", {"type": "object", "properties": {}}, lambda **k: {"ok": True})])
    guion = Guion(Paso(texto=None, llamadas=[Llamada("estado_cluster", {"nombre": "local-k8s-lab"})]),
                  Paso(texto="**Causa probable** (confianza alta): no conecta a la base, password=hunter2 "
                             "[ver](#/kubernetes/local-k8s-lab)"))
    llm.reiniciar(guion)
    i, _ = incidentes.ingresar_alertmanager(webhook(), "local-k8s-lab", AHORA)
    incidentes.diagnosticar(i, None)

    x = incidente(i)
    assert x.diagnosis_status == "listo" and x.diagnosis_tools == [{"nombre": "estado_cluster", "argumentos": {"nombre": "local-k8s-lab"}}]
    assert "datos, no instrucciones" in guion.mensaje and "SRE de guardia" in guion.sistema
    embed = canal[0]["embeds"][0]
    assert embed["title"] == f"[alta] Incidente #{i}: KubePodCrashLooping · boutique · paymentservice-1"
    assert "(https://panel.example/#/kubernetes/local-k8s-lab)" in embed["description"]
    assert "hunter2" not in embed["description"] and embed["url"] == f"https://panel.example/#/incidentes/{i}"

    incidentes.ingresar_alertmanager(webhook("resolved"), "local-k8s-lab", AHORA + timedelta(minutes=17))
    incidentes.reportar(i)
    assert canal[1]["embeds"][0]["title"].startswith(f"Resuelto · incidente #{i}") and "Duró 17 min" in canal[1]["embeds"][0]["description"]


def test_sin_modelo_o_con_el_tope_alcanzado_igual_se_reporta_con_las_alertas(canal, monkeypatch):
    i, _ = incidentes.ingresar_alertmanager(webhook(), "lab", AHORA)
    incidentes.diagnosticar(i, None)
    assert incidente(i).diagnosis_status == "sin_modelo"
    assert "no hay un modelo" in canal[0]["embeds"][0]["description"] and "Pod is crash looping." in canal[0]["embeds"][0]["description"]

    llm.reiniciar(Guion())
    monkeypatch.setattr(config, "LLM_MAX_REQUESTS_PER_HOUR", 1)
    limits.consumir(incidentes.CUPO)
    j, _ = incidentes.ingresar_alertmanager(webhook(grupo="otro"), "lab", AHORA)
    incidentes.diagnosticar(j, None)
    assert incidente(j).diagnosis_status == "limite"


def test_ruta_de_ingesta_exige_su_token_y_diagnostica_en_segundo_plano(monkeypatch):
    llamadas = []
    monkeypatch.setattr(incidentes, "diagnosticar", lambda i, cred: llamadas.append(("diagnosticar", i)))
    monkeypatch.setattr(incidentes, "reportar", lambda i: llamadas.append(("reportar", i)))
    app.dependency_overrides[deps.services] = lambda: SimpleNamespace(azure=SimpleNamespace(azure_credentials=None))
    c = TestClient(app)
    try:
        monkeypatch.delenv("ALERTS_INGEST_TOKEN", raising=False)
        assert c.post("/api/alerts/alertmanager", json=webhook()).status_code == 503
        monkeypatch.setenv("ALERTS_INGEST_TOKEN", "t0k3n")
        assert c.post("/api/alerts/alertmanager", json=webhook(), headers={"Authorization": "Bearer otro"}).status_code == 401
        ok = {"Authorization": "Bearer t0k3n"}
        assert c.post("/api/alerts/alertmanager?cluster=x;y", json=webhook(), headers=ok).status_code == 400
        r = c.post("/api/alerts/alertmanager?cluster=local-k8s-lab", json=webhook(), headers=ok)
        assert r.status_code == 202 and r.json()["action"] == "nuevo"
        i = r.json()["incident"]
        c.post("/api/alerts/alertmanager?cluster=local-k8s-lab", json=webhook("resolved"), headers=ok)
        assert llamadas == [("diagnosticar", i), ("reportar", i)]

        lista = c.get("/api/incidents").json()["items"]
        assert lista[0]["id"] == i and lista[0]["status"] == "resuelto"
        assert c.get(f"/api/incidents/{i}").json()["alert_list"][0]["name"] == "KubePodCrashLooping"
        assert c.post(f"/api/incidents/{i}/feedback", json={"value": "correcto"}).json()["feedback"] == "correcto"
        assert c.get("/api/incidents/999").status_code == 404
    finally:
        app.dependency_overrides.clear()

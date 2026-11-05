"""
Gestión de incidentes (bloque 1): silencios, tormentas, ciclo de vida, línea de
tiempo, ajustes, post-mortem y precisión, con base SQLite y un modelo simulado.
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
from app.core import ajustes, config, deps  # noqa: E402
from app.db import engine as db  # noqa: E402
from app.db.models import Base, Incident  # noqa: E402
from app.llm import limits  # noqa: E402
from app.llm.base import Respuesta  # noqa: E402
from app.main import app  # noqa: E402

AHORA = datetime.now(timezone.utc)


def webhook(pod="paymentservice-1", status="firing", alerta="PodCrashLooping", severidad="warning", ns="boutique"):
    return {"version": "4", "status": status, "groupKey": f"{{}}:{{namespace=\"{ns}\", pod=\"{pod}\"}}",
            "alerts": [{"status": status, "startsAt": "2026-11-05T04:06:10Z", "endsAt": "0001-01-01T00:00:00Z",
                        "labels": {"alertname": alerta, "namespace": ns, "pod": pod, "severity": severidad},
                        "annotations": {"summary": f"Pod {pod} en CrashLoopBackOff"}}],
            "commonLabels": {"alertname": alerta, "namespace": ns, "pod": pod}}


@pytest.fixture(autouse=True)
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'i.db'}")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    limits.reiniciar()
    yield
    db.reset_engine()
    llm.reiniciar(None)
    limits.reiniciar()


@pytest.fixture
def cliente():
    app.dependency_overrides[deps.services] = lambda: SimpleNamespace(azure=SimpleNamespace(azure_credentials=None))
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def leer(i):
    with db.session_scope() as s:
        x = s.get(Incident, i)
        return SimpleNamespace(**{c.name: getattr(x, c.name) for c in Incident.__table__.columns})


def test_lo_silenciado_no_abre_incidente_y_un_silencio_vence():
    s = ajustes.silenciar("ana@x", 1, "mantenimiento", cluster="lab", namespace="boutique", objeto="payment")
    assert incidentes.ingresar_alertmanager(webhook(), "lab", AHORA) == (None, "silenciado")
    # Otro clúster u otro pod: no coincide.
    assert incidentes.ingresar_alertmanager(webhook(), "otro", AHORA)[1] == "nuevo"
    assert incidentes.ingresar_alertmanager(webhook("cartservice-1"), "lab", AHORA)[1] == "nuevo"
    assert ajustes.quitar_silencio(s["id"]) and ajustes.silencios() == []
    with pytest.raises(ValueError):
        ajustes.silenciar("ana@x", 1, "todo")  # sin alcance: no se silencia todo
    with pytest.raises(ValueError):
        ajustes.silenciar("ana@x", 24 * 31, "mucho", cluster="lab")


def test_una_tormenta_cuelga_del_primero_y_se_diagnostica_una_vez(monkeypatch):
    acciones = [incidentes.ingresar_alertmanager(webhook(f"svc{n}-1"), "lab", AHORA + timedelta(seconds=n * 10))
                for n in range(5)]
    assert [a for _, a in acciones] == ["nuevo", "nuevo", "tormenta", "agrupado", "agrupado"]
    padre = acciones[0][0]
    assert acciones[2][0] == padre  # la tormenta devuelve el padre, que se vuelve a diagnosticar
    assert leer(padre).title == "Tormenta en lab: 5 incidentes · PodCrashLooping · boutique · svc0-1"
    hijos = [leer(i) for i in range(padre + 1, padre + 5)]  # los ids son consecutivos
    assert {h.parent_id for h in hijos} == {padre} and {h.diagnosis_status for h in hijos[1:]} == {"agrupado"}
    # Fuera de la ventana (2 min) u otro clúster: incidente propio.
    assert incidentes.ingresar_alertmanager(webhook("tarde-1"), "lab", AHORA + timedelta(minutes=10))[1] == "nuevo"

    # El diagnóstico del padre lleva las alertas de todos y pide la causa común.
    vistos = {}

    class Modelo:
        nombre, modelo = "f", "f"

        def iniciar(self, mensaje):
            vistos["mensaje"] = mensaje
            return []

        def paso(self, sistema, historial, decls):
            from app.llm.base import Paso
            return Paso(texto="**Causa probable** (confianza alta): se reinició la máquina.")

        def agregar_resultados(self, h, r):
            pass

    llm.reiniciar(Modelo())
    incidentes.diagnosticar(padre, None)
    assert "Es una tormenta: 5 incidentes" in vistos["mensaje"] and "svc4-1" in vistos["mensaje"]
    assert leer(padre).diagnosis_status == "listo"


def test_los_hijos_y_las_severidades_que_no_se_avisan_no_salen_al_canal(monkeypatch):
    from app.collectors import notify
    enviados = []
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://discord.com/api/webhooks/1/SECRETO")
    monkeypatch.setattr(notify.requests, "post", lambda url, json=None, timeout=None: enviados.append(json) or SimpleNamespace(status_code=204))
    for n in range(3):
        incidentes.ingresar_alertmanager(webhook(f"svc{n}-1"), "lab", AHORA)
    incidentes.reportar(3)  # el tercero: hijo de la tormenta
    assert enviados == []
    ajustes.guardar_incidentes({"avisar": ["critica"], "diagnosticar": ["critica"]})
    j, _ = incidentes.ingresar_alertmanager(webhook("solo-1"), "otro", AHORA)
    incidentes.diagnosticar(j, None)
    assert leer(j).diagnosis_status == "omitido" and enviados == []


def test_ajustes_validan_tipos_y_rangos():
    assert ajustes.incidentes()["umbral_tormenta"] == 3
    with pytest.raises(ValueError):
        ajustes.guardar_incidentes({"umbral_tormenta": 1})
    with pytest.raises(ValueError):
        ajustes.guardar_incidentes({"avisar": ["urgente"]})
    with pytest.raises(ValueError):
        ajustes.guardar_incidentes({"inventado": 1})
    with pytest.raises(ValueError):
        ajustes.guardar_incidentes({"postmortem": 1})
    assert ajustes.guardar_incidentes({"umbral_tormenta": 4})["umbral_tormenta"] == 4
    assert ajustes.guardar_cluster("lab", {"namespaces_ignorados": ["b", "a", "a"]})["namespaces_ignorados"] == ["a", "b"]
    assert ajustes.cluster("otro") == ajustes.CLUSTER


def test_tope_propio_de_diagnosticos_por_hora(monkeypatch):
    monkeypatch.setattr(config, "LLM_MAX_REQUESTS_PER_HOUR", 30)
    limits.consumir("x", por_hora=1)
    with pytest.raises(limits.LimiteExcedido):
        limits.consumir("x", por_hora=1)


def test_ciclo_de_vida_linea_de_tiempo_filtros_y_precision(cliente, monkeypatch):
    i, _ = incidentes.ingresar_alertmanager(webhook(), "lab", AHORA)
    j, _ = incidentes.ingresar_alertmanager(webhook("otro-1", severidad="critical"), "lab2", AHORA)

    assert cliente.post(f"/api/incidents/{i}/status", json={"status": "cerrado"}).status_code == 400  # sin motivo
    r = cliente.post(f"/api/incidents/{i}/status", json={"status": "reconocido", "comment": "lo miro"}).json()
    assert r["status"] == "reconocido" and r["assignee"]  # quien lo toma queda de responsable
    cliente.post(f"/api/incidents/{i}/assign", json={"assignee": "bob@x"})
    cliente.post(f"/api/incidents/{i}/notes", json={"text": "Reinicié el nodo"})
    # Sigue vivo para la fuente: una alerta del mismo grupo lo actualiza, no abre otro.
    assert incidentes.ingresar_alertmanager(webhook(), "lab", AHORA) == (i, "actualizado")
    assert cliente.post(f"/api/incidents/{i}/status", json={"status": "cerrado", "reason": "ruido"}).json()["status"] == "cerrado"
    assert cliente.post(f"/api/incidents/{i}/status", json={"status": "en_curso"}).status_code == 200  # reabre a en curso
    cliente.post(f"/api/incidents/{i}/status", json={"status": "cerrado", "reason": "falso_positivo"})

    d = cliente.get(f"/api/incidents/{i}").json()
    assert d["assignee"] == "bob@x" and d["closed_reason"] == "falso_positivo"
    tipos = [e["kind"] for e in d["events"]]
    assert tipos[0] == "abierto" and {"estado", "asignado", "nota"} <= set(tipos)
    assert any(e["text"] == "Reinicié el nodo" for e in d["events"])

    assert [x["id"] for x in cliente.get("/api/incidents?estado=vivos").json()["items"]] == [j]
    assert [x["id"] for x in cliente.get("/api/incidents?severidad=critica").json()["items"]] == [j]
    assert [x["id"] for x in cliente.get("/api/incidents?cluster=lab").json()["items"]] == [i]

    cliente.post(f"/api/incidents/{j}/feedback", json={"value": "correcto"})
    m = cliente.get("/api/incidents/stats").json()
    assert (m["total"], m["open"], m["marked"], m["accuracy"], m["noise"]) == (2, 1, 1, 1.0, 1)

    incidentes.diagnosticar(j, None)  # sin modelo: termina enseguida
    llamadas = []
    monkeypatch.setattr(incidentes, "diagnosticar", lambda *a: llamadas.append(a))
    assert cliente.post(f"/api/incidents/{j}/rediagnose").status_code == 202 and llamadas[0][0] == j
    assert cliente.post(f"/api/incidents/{j}/rediagnose").status_code == 409  # ya está diagnosticando


def test_post_mortem_al_resolverse(cliente, monkeypatch):
    class Modelo:
        nombre, modelo = "f", "f"

        def generar(self, sistema, mensaje, **k):
            self.mensaje = mensaje
            return Respuesta(texto="**Resumen** se cayó paymentservice", modelo="f")

    modelo = Modelo()
    llm.reiniciar(modelo)
    i, _ = incidentes.ingresar_alertmanager(webhook(), "lab", AHORA)
    cliente.post(f"/api/incidents/{i}/notes", json={"text": "rollback hecho"})
    assert incidentes.ingresar_alertmanager(webhook(status="resolved"), "lab", AHORA + timedelta(minutes=9)) == (i, "resuelto")
    incidentes.al_resolverse(i)
    assert leer(i).postmortem.startswith("**Resumen**") and "rollback hecho" in modelo.mensaje
    assert cliente.get(f"/api/incidents/{i}").json()["events"][-1]["kind"] == "postmortem"

    ajustes.guardar_incidentes({"postmortem": False})
    k, _ = incidentes.ingresar_alertmanager(webhook("b-1"), "lab", AHORA)
    incidentes.ingresar_alertmanager(webhook("b-1", status="resolved"), "lab", AHORA)
    incidentes.al_resolverse(k)
    assert leer(k).postmortem is None
    assert cliente.post(f"/api/incidents/{k}/postmortem").json()["postmortem"].startswith("**Resumen**")


def test_silencios_y_ajustes_por_la_api(cliente):
    assert cliente.post("/api/silences", json={"hours": 2}).status_code == 400
    s = cliente.post("/api/silences", json={"hours": 2, "cluster": "lab", "alertname": "PodCrashLooping"}).json()
    assert [x["id"] for x in cliente.get("/api/silences").json()["items"]] == [s["id"]]
    assert cliente.delete(f"/api/silences/{s['id']}").json()["removed"] and cliente.delete(f"/api/silences/{s['id']}").status_code == 404
    assert cliente.put("/api/settings/incidents", json={"foto_vieja_min": 2}).status_code == 400
    assert cliente.put("/api/settings/incidents", json={"foto_vieja_min": 30}).json()["values"]["foto_vieja_min"] == 30
    assert cliente.get("/api/settings/incidents").json()["values"]["foto_vieja_min"] == 30

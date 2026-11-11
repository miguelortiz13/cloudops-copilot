"""Fase 7.1 (plan 12): diagnósticos sin marcar, alertas ruidosas y acciones del post-mortem en Mis pendientes."""

import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import ajustes, config, deps  # noqa: E402
from app.db import engine as db  # noqa: E402
from app.db.models import Base, Incident  # noqa: E402
from app.dominios.inicio import servicio  # noqa: E402

AHORA = datetime.now(timezone.utc)
YO = "Desarrollo local"  # el actor de las rutas sin autenticación
POSTMORTEM = "**Resumen**\nCayó pagos.\n\n**Acciones**\n- Fijar el tag de la imagen\n- Alertar ImagePullBackOff\n\n**Notas**\n- nada"


def incidente(id_, *, cierre=None, feedback=None, diagnostico="listo", hace_h=2, alerta="KubePodCrashLooping", quien=None,
              postmortem=None):
    t = AHORA - timedelta(hours=hace_h)
    return Incident(id=id_, key=f"k{id_}", source="alertmanager", cluster="lab", title=f"{alerta} · boutique · svc{id_}",
                    severity="alta", status="cerrado" if cierre else "resuelto", alerts=[{"name": alerta}], opened_at=t,
                    last_alert_at=t, resolved_at=t + timedelta(minutes=10), diagnosis_status=diagnostico,
                    diagnosis="Causa probable: x", feedback=feedback, closed_reason=cierre, assignee=quien, postmortem=postmortem)


@pytest.fixture(autouse=True)
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'c.db'}")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    yield
    db.reset_engine()


def sembrar(*incidentes):
    with db.session_scope() as s:
        s.add_all(incidentes)


def tipos(tipo):
    return [p for p in servicio.pendientes(YO, AHORA) if p["type"] == tipo]


def test_diagnosticos_sin_marcar_sueltos_o_agrupados():
    sembrar(incidente(1), incidente(2), incidente(3, feedback="correcto"), incidente(4, cierre="ruido"),
            incidente(5, diagnostico="limite"), incidente(6, hace_h=24 * 20), incidente(7, quien="otro@x"))
    assert [p["link"] for p in tipos("marcar")] == ["#/operacion/incidentes/1", "#/operacion/incidentes/2"]
    sembrar(*(incidente(n) for n in range(10, 13)))
    agrupado = tipos("marcar")
    assert len(agrupado) == 1 and agrupado[0]["title"] == "5 incidentes resueltos sin marcar el diagnóstico"


def test_alerta_ruidosa_hasta_que_se_silencia():
    sembrar(incidente(1, cierre="ruido"), incidente(2, cierre="falso_positivo", hace_h=30), incidente(3, cierre="ruido", alerta="Otra"))
    ruido = tipos("ruido")
    assert [(p["title"], p["link"]) for p in ruido] == [("KubePodCrashLooping en lab", "#/operacion/incidentes/1")]
    assert "2 veces" in ruido[0]["why"]
    ajustes.silenciar("ana@x", 24, "ruido conocido", cluster="lab", alerta="KubePodCrashLooping")
    assert tipos("ruido") == []


def test_acciones_del_postmortem_como_pendientes():
    sembrar(incidente(1, cierre="solucionado", postmortem=POSTMORTEM, quien=YO), incidente(2))
    from app.main import app
    app.dependency_overrides[deps.services] = lambda: SimpleNamespace(azure=SimpleNamespace(azure_credentials=None))
    try:
        c = TestClient(app)
        r = c.post("/api/incidents/1/actions", json={"from_postmortem": True}).json()["items"]
        assert [(a["text"], a["owner"]) for a in r] == [("Fijar el tag de la imagen", YO), ("Alertar ImagePullBackOff", YO)]
        assert c.post("/api/incidents/1/actions", json={"from_postmortem": True}).json()["items"] == []  # no se repiten
        assert c.post("/api/incidents/2/actions", json={"from_postmortem": True}).status_code == 409
        assert c.post("/api/incidents/1/actions", json={"text": " "}).status_code == 400
        assert [p["title"] for p in tipos("accion")] == ["Fijar el tag de la imagen", "Alertar ImagePullBackOff"]

        c.post(f"/api/incidents/1/actions/{r[0]['id']}", json={"done": True})
        c.post(f"/api/incidents/1/actions/{r[1]['id']}", json={"owner": "otro@x"})
        assert tipos("accion") == []  # una hecha, la otra de otra persona
        detalle = c.get("/api/incidents/1").json()
        assert detalle["actions"][0]["done_at"] and detalle["actions"][1]["owner"] == "otro@x"
        assert sum(e["kind"] == "accion" for e in detalle["events"]) == 2  # creadas + hecha
        assert c.post("/api/incidents/2/actions/1", json={"done": True}).status_code == 404  # de otro incidente
    finally:
        app.dependency_overrides.clear()

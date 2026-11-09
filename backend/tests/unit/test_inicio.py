"""Dominio Inicio (fase 5 del plan 10): Mis pendientes y Qué cambió."""

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
from app.db.models import Account, Base, ControlException, CostEvent, Finding, Incident, Resource, Rule  # noqa: E402
from app.dominios.inicio import servicio  # noqa: E402

AHORA = datetime.now(timezone.utc)
HOY = AHORA.date()
YO = "ana@contoso.example"


@pytest.fixture(autouse=True)
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'i.db'}")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    with db.session_scope() as s:
        s.add(Account(uid="azure:sub/1", provider="azure", native_id="1", name="sub", first_seen=AHORA, last_seen=AHORA))
        s.add(Rule(id="storage.public", capability="secops", title="Acceso público", severity_default="alta"))
        for n, (nuevo, iac, borrado) in enumerate([(True, False, None), (False, True, AHORA - timedelta(hours=2)), (False, True, None)]):
            s.add(Resource(uid=f"azure:r{n}", provider="azure", account_uid="azure:sub/1", name=f"r{n}", native_type="x",
                           in_iac_state=iac, first_seen=AHORA - (timedelta(hours=1) if nuevo else timedelta(days=60)),
                           last_seen=AHORA, deleted_at=borrado))
        inc = lambda id_, sev, quien=None, estado="abierto", hace=1: Incident(  # noqa: E731
            id=id_, key=f"k{id_}", source="alertmanager", cluster="lab", title=f"Alerta {id_}", severity=sev, status=estado,
            alerts=[], opened_at=AHORA - timedelta(hours=hace), last_alert_at=AHORA, assignee=quien)
        s.add_all([inc(1, "media", YO), inc(2, "critica"), inc(3, "media"), inc(4, "alta", "otro@x"),
                   inc(5, "alta", YO, "resuelto", hace=200)])
        hallazgo = lambda id_, uid, **kw: Finding(id=id_, rule_id="storage.public", resource_uid=uid, account_uid="azure:sub/1",  # noqa: E731
                                                  severity=kw.pop("sev", "alta"), first_seen=kw.pop("visto", AHORA - timedelta(days=60)),
                                                  last_seen=AHORA, **kw)
        s.add_all([hallazgo(1, "azure:r0", owner=YO, due_date=HOY - timedelta(days=2)),
                   hallazgo(2, "azure:r1", status="aceptado", accepted_until=HOY + timedelta(days=3)),
                   hallazgo(3, "azure:r2", sev="critica", visto=AHORA - timedelta(hours=3)),
                   hallazgo(4, "azure:x/r9", status="aceptado", accepted_until=HOY + timedelta(days=90))])
        s.add(CostEvent(key="a1", kind="presupuesto", provider="azure", amount=9, title="Presupuesto al 100 %",
                        opened_at=AHORA - timedelta(hours=5), updated_at=AHORA))
        s.add(ControlException(framework="cis", control="8.7", justification="x", created_by=YO, created_at=AHORA,
                               until=HOY + timedelta(days=10)))
    ajustes.silenciar(YO, 2, "mantenimiento", cluster="lab")
    ajustes.silenciar("otro@x", 2, "otro", cluster="lab2")
    yield
    db.reset_engine()


def test_mis_pendientes_por_urgencia_y_con_el_porque():
    items = servicio.pendientes(YO, AHORA)
    resumen = [(i["type"], i["urgency"], i["why"]) for i in items]
    # Hallazgo propio atrasado (alta + 1 = 3) y crítico sin responsable primero; nada del otro ni lo resuelto.
    assert resumen[:2] == [("hallazgo", 3, f"Asignado a ti · vencido el {(HOY - timedelta(days=2)).isoformat()}"),
                           ("incidente", 3, "Severidad critica y sin responsable")]
    tipos = [i["type"] for i in items]
    assert tipos.count("incidente") == 2 and "#/operacion/incidentes/1" in [i["link"] for i in items]
    assert any(i["why"] == "Riesgo aceptado: vence en 3 día(s)" for i in items)
    assert sum(1 for i in items if i["type"] == "hallazgo") == 2  # el aceptado a 90 días no aparece
    assert any(i["type"] == "costo" and i["urgency"] == 2 for i in items)
    assert any(i["type"] == "excepcion" and "10 día(s)" in i["why"] for i in items)
    assert [i["title"] for i in items if i["type"] == "silencio"] == ["Silencio lab"]


def test_que_cambio_desde_la_ultima_visita():
    c = servicio.cambios(AHORA - timedelta(hours=24))
    assert c["incidents"]["new"] == 4 and c["incidents"]["latest"][0]["id"] == 1
    assert c["findings"] == {"new": 1, "new_critical": 1, "resolved": 0}
    assert c["resources"] == {"new": 1, "new_outside_iac": 1, "deleted": 1}
    assert c["cost_alerts"]["new"] == 1


def test_rutas_con_el_usuario_que_consulta():
    from app.main import app
    app.dependency_overrides[deps.services] = lambda: SimpleNamespace(azure=SimpleNamespace(azure_credentials=None))
    try:
        c = TestClient(app)
        r = c.get("/api/inicio/pendientes").json()
        assert r["configured"] and r["items"][0]["urgency"] == 3
        assert c.get("/api/inicio/cambios", params={"desde": (AHORA - timedelta(hours=2)).isoformat()}).json()["incidents"]["new"] == 4
        assert c.get("/api/inicio/cambios", params={"desde": (AHORA + timedelta(days=1)).isoformat()}).status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_la_ia_prioriza_con_el_detalle_y_recuerda_la_respuesta(monkeypatch):
    from app import llm
    from app.llm import limits
    from app.llm.base import Respuesta

    class Modelo:
        nombre, modelo, mensajes = "falso", "falso-1", []

        def generar(self, sistema, mensaje, **k):
            self.mensajes.append((sistema, mensaje))
            return Respuesta(texto="**Por dónde empezar:**\n- Reconoce [#2](#/operacion/incidentes/2)", modelo="falso-1")

    with db.session_scope() as s:
        s.get(Incident, 2).diagnosis = "Causa probable: imagen v9.9.9 inexistente"
    m = Modelo()
    llm.reiniciar(m)
    servicio._CACHE.clear()
    limits.reiniciar()
    try:
        from app.main import app
        app.dependency_overrides[deps.services] = lambda: SimpleNamespace(azure=SimpleNamespace(azure_credentials=None))
        c = TestClient(app)
        r = c.post("/api/inicio/pendientes/priorizar").json()
        assert r["text"].startswith("**Por dónde empezar:**") and r["cached"] is False
        sistema, mensaje = m.mensajes[0]
        assert "Por dónde empezar" in sistema and "<<<DATOS_NO_CONFIABLES>>>" in mensaje
        assert "#/operacion/incidentes/2" in mensaje and "imagen v9.9.9 inexistente" in mensaje  # el porqué y el detalle llegan al modelo
        assert c.post("/api/inicio/pendientes/priorizar").json()["cached"] is True and len(m.mensajes) == 1
        llm.reiniciar(None)
        assert c.post("/api/inicio/pendientes/priorizar").status_code == 503
    finally:
        app.dependency_overrides.clear()
        llm.reiniciar(None)
        limits.reiniciar()

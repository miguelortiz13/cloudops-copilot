"""Tablero de valor (fase 7.2, plan 12): indicadores por semana, tendencia en el resumen y el reporte."""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import config, deps  # noqa: E402
from app.db import engine as db  # noqa: E402
from app.db.models import Account, Base, Finding, FindingEvent, Incident, IncidentEvent, Rule  # noqa: E402
from app.dominios.inicio import valor  # noqa: E402

AHORA = datetime(2026, 11, 12, 15, tzinfo=timezone.utc)  # jueves de la semana 2026-W46
SEMANA_PASADA = datetime(2026, 11, 3, 10, tzinfo=timezone.utc)  # martes de 2026-W45


def incidente(id_, abierto, *, minutos=None, reconocer=None, cierre=None, feedback=None):
    i = Incident(id=id_, key=f"k{id_}", source="alertmanager", cluster="lab", title=f"Alerta {id_}", severity="alta",
                 status="resuelto" if minutos else "abierto", alerts=[], opened_at=abierto, last_alert_at=abierto,
                 resolved_at=abierto + timedelta(minutes=minutos) if minutos else None, diagnosis_status="listo",
                 diagnosis="x", closed_reason=cierre, feedback=feedback)
    eventos = [IncidentEvent(incident_id=id_, at=abierto + timedelta(minutes=1), actor="agente", kind="diagnostico", text="x")]
    if reconocer is not None:
        eventos.append(IncidentEvent(incident_id=id_, at=abierto + timedelta(minutes=reconocer), actor="ana@x", kind="estado", text="Reconocido"))
    return [i, *eventos]


@pytest.fixture(autouse=True)
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'v.db'}")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    with db.session_scope() as s:
        s.add(Account(uid="azure:sub/1", provider="azure", native_id="1", name="sub", first_seen=AHORA, last_seen=AHORA))
        s.add(Rule(id="r", capability="secops", title="Regla", severity_default="alta"))
        s.add_all(incidente(1, SEMANA_PASADA, minutos=60, reconocer=20, feedback="correcto")
                  + incidente(2, SEMANA_PASADA + timedelta(hours=3), minutos=30, cierre="ruido")
                  + incidente(3, SEMANA_PASADA + timedelta(hours=5), minutos=90, reconocer=10, feedback="incorrecto")
                  + incidente(4, AHORA - timedelta(hours=5), minutos=20, reconocer=4)
                  + incidente(5, AHORA - timedelta(hours=1)))
        s.add(Finding(id=1, rule_id="r", resource_uid="x", account_uid="azure:sub/1", severity="critica", status="resuelto",
                      first_seen=SEMANA_PASADA - timedelta(days=4), last_seen=AHORA, resolved_at=SEMANA_PASADA))
        s.add(Finding(id=2, rule_id="r", resource_uid="y", account_uid="azure:sub/1", severity="alta", status="abierto",
                      first_seen=AHORA - timedelta(days=1), last_seen=AHORA))
        s.add_all([FindingEvent(finding_id=1, at=SEMANA_PASADA, kind="resuelto", actor="recolector"),
                   FindingEvent(finding_id=2, at=AHORA - timedelta(days=1), kind="detectado", actor="recolector")])
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals" / "historial.jsonl").write_text(json.dumps({"at": "2026-11-09T07:10:00Z", "suites": [
        {"suite": "asistente", "accuracy": 1.0, "target": 0.9}, {"suite": "inyeccion", "accuracy": 0.86, "target": 1.0}]}) + "\n")
    yield
    db.reset_engine()


def test_indicadores_por_semana():
    t = valor.tablero(2, AHORA)
    pasada, actual = t["weeks"]
    assert (pasada["week"], actual["week"]) == ("2026-W45", "2026-W46")
    assert pasada["incidents"] == {"total": 3, "mtta_min": 20.0, "mttr_min": 60.0, "noise_pct": 33.3,
                                   "marked_pct": 100.0, "correct_pct": 50.0}  # el de ruido no pide marca
    assert actual["incidents"]["total"] == 2 and actual["incidents"]["mtta_min"] == 4.0 and actual["incidents"]["marked_pct"] == 0.0
    assert pasada["findings"] == {"detected": 0, "resolved": 1, "days_to_close": 4.0}
    assert actual["findings"]["detected"] == 1 and t["findings_open"] == 1
    assert t["evals"]["on_target"] == 1 and len(t["evals"]["suites"]) == 2
    assert "realized_monthly" in t["savings"]


def test_tendencia_y_resumen_semanal_y_reporte_mensual():
    t = valor.tendencia(datetime(2026, 11, 16, 6, tzinfo=timezone.utc))  # lunes: cierra W45 y W46
    assert (t["semana_anterior"]["week"], t["ultima_semana"]["week"]) == ("2026-W45", "2026-W46")
    from app.collectors import semanal
    from app.reports import mensual
    with db.session_scope() as s:
        d = semanal.datos(s, date(2026, 11, 16))
        m = mensual.datos(s, date(2026, 11, 1))
    assert d["tendencia"]["ultima_semana"]["semana"] == "2026-W46" and d["tendencia"]["semana_anterior"]["mtta_min"] == 20.0
    assert m["incidentes"]["mediana_min_para_reconocer"] == 10


def test_ruta():
    from app.main import app
    app.dependency_overrides[deps.services] = lambda: SimpleNamespace(azure=SimpleNamespace(azure_credentials=None))
    try:
        c = TestClient(app)
        r = c.get("/api/inicio/valor", params={"semanas": 4}).json()
        assert r["configured"] and len(r["weeks"]) == 4
        assert c.get("/api/inicio/valor", params={"semanas": 1}).status_code == 422
    finally:
        app.dependency_overrides.clear()

"""Asignación por reglas (fase 7, plan 12): incidentes por clúster, namespace o alerta; hallazgos por la tag Owner."""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402

from app.ai import incidentes  # noqa: E402
from app.core import ajustes, config  # noqa: E402
from app.db import engine as db  # noqa: E402
from app.db.models import Account, Base, Finding, Incident, IncidentEvent, Resource, Rule  # noqa: E402
from app.dominios.inicio import servicio, valor  # noqa: E402

AHORA = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'a.db'}")
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    yield
    db.reset_engine()


def alerta(nombre, namespace, grupo):
    return {"status": "firing", "groupKey": grupo, "commonLabels": {"alertname": nombre},
            "alerts": [{"status": "firing", "labels": {"alertname": nombre, "namespace": namespace, "severity": "warning"},
                        "annotations": {"summary": "x"}, "startsAt": AHORA.isoformat()}]}


def test_reglas_validas_y_en_orden():
    with pytest.raises(ValueError, match="campo:valor=responsable"):
        ajustes.guardar("asignacion", {"reglas_asignacion": ["equipo:pagos=ana@x"]})
    ajustes.guardar("asignacion", {"reglas_asignacion": ["namespace:boutique=ana@x", "cluster:lab=ops@x", "alerta:HttpCheckFailed=web@x"]})
    assert ajustes.responsable_por_reglas("lab", ["boutique"], ["X"]) == ("ana@x", "namespace:boutique=ana@x")  # la primera gana
    assert ajustes.responsable_por_reglas("lab", ["monitoring"], ["X"])[0] == "ops@x"
    assert ajustes.responsable_por_reglas(None, [], ["HttpCheckFailed"])[0] == "web@x"
    assert ajustes.responsable_por_reglas("otro", [], ["X"]) is None


def test_el_incidente_nuevo_toma_responsable_y_no_cuenta_como_reconocido():
    ajustes.guardar("asignacion", {"reglas_asignacion": ["namespace:boutique=ana@x"]})
    i, _ = incidentes.ingresar_alertmanager(alerta("KubePodCrashLooping", "boutique", "g1"), "lab", AHORA)
    j, _ = incidentes.ingresar_alertmanager(alerta("KubePodCrashLooping", "monitoring", "g2"), "lab", AHORA)
    with db.session_scope() as s:
        assert s.get(Incident, i).assignee == "ana@x" and s.get(Incident, j).assignee is None
        ev = s.query(IncidentEvent).filter_by(incident_id=i, kind="asignado").one()
        assert ev.actor == "reglas" and "namespace:boutique=ana@x" in ev.text
    assert [p["why"] for p in servicio.pendientes("ana@x") if p["link"].endswith(f"/{i}")] == ["Asignado a ti · abierto"]
    assert valor.tablero(2)["weeks"][-1]["incidents"]["mtta_min"] is None  # la regla no es una persona


def test_hallazgo_sin_responsable_por_la_tag_owner():
    with db.session_scope() as s:
        s.add(Account(uid="azure:sub/1", provider="azure", native_id="1", name="sub", first_seen=AHORA, last_seen=AHORA))
        s.add(Rule(id="r", capability="secops", title="Acceso público", severity_default="alta"))
        s.add(Resource(uid="azure:r1", provider="azure", account_uid="azure:sub/1", name="stdatos", native_type="x",
                       tags={"owner": "Ana@X"}, first_seen=AHORA, last_seen=AHORA))
        s.add(Finding(rule_id="r", resource_uid="azure:r1", account_uid="azure:sub/1", severity="alta",
                      first_seen=AHORA - timedelta(days=1), last_seen=AHORA))
    mios = [p for p in servicio.pendientes("ana@x") if p["type"] == "hallazgo"]
    assert [(p["title"], p["why"]) for p in mios] == [("Acceso público · stdatos", "Sin responsable; el recurso tiene tu correo en la tag Owner")]
    assert [p for p in servicio.pendientes("otro@x") if p["type"] == "hallazgo"] == []

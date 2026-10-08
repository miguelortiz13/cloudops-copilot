"""
Autorizacion por rol y auditoria.

Se activa AUTH_ENABLED y se sustituye solo la validacion criptografica del
token: el resto del camino (middleware, claims, roles, dependencias) es el
real. El token "operador" lleva el app role CloudOps.Operator, etc.
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import config  # noqa: E402
from app.db import engine as db  # noqa: E402
from app.db.models import AuditLog, Base, Finding, Rule  # noqa: E402
from app.services import auth  # noqa: E402

APP_ROLES = {
    "sin-rol": [],
    "lector": ["CloudOps.Reader"],
    "operador": ["CloudOps.Operator"],
    "admin": ["CloudOps.Admin"],
    "varios": ["CloudOps.Reader", "CloudOps.Admin"],
}


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'a.db'}")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "validate_token", lambda token: {
        "oid": f"oid-{token}", "name": token.title(), "preferred_username": f"{token}@contoso.com",
        "roles": APP_ROLES[token],
    })
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    with db.session_scope() as s:
        s.add(Rule(id="r1", capability="security", title="Regla", severity_default="alta", frameworks={}))
        t = datetime(2026, 10, 1, tzinfo=timezone.utc)
        s.add(Finding(rule_id="r1", resource_uid="azure:/x", account_uid="azure:sub/s", severity="alta",
                      status="abierto", details={}, first_seen=t, last_seen=t))
    from app.main import app

    yield TestClient(app)
    db.reset_engine()


def como(token):
    return {"Authorization": f"Bearer {token}"}


def test_sin_token_401(cliente):
    assert cliente.get("/api/findings").status_code == 401


@pytest.mark.parametrize("token,rol", [("sin-rol", "lector"), ("lector", "lector"), ("operador", "operador"),
                                        ("admin", "administrador"), ("varios", "administrador")])
def test_rol_efectivo(cliente, token, rol):
    yo = cliente.get("/api/me", headers=como(token)).json()
    assert yo["role"] == rol
    assert yo["upn"] == f"{token}@contoso.com"


def test_un_lector_lee_pero_no_gestiona(cliente):
    assert cliente.get("/api/findings", headers=como("lector")).status_code == 200
    r = cliente.post("/api/findings/1/status", headers=como("lector"), json={"status": "asumido"})
    assert r.status_code == 403
    assert "operador" in r.json()["detail"]


def test_asignado_sin_app_role_no_escribe(cliente):
    r = cliente.post("/api/findings/1/status", headers=como("sin-rol"), json={"status": "asumido"})
    assert r.status_code == 403


def test_el_operador_gestiona_y_queda_auditado(cliente):
    r = cliente.post("/api/findings/1/status", headers=como("operador"), json={"status": "asumido", "note": "Lo tomo"})
    assert r.status_code == 200
    assert r.json()["owner"] == "operador@contoso.com"
    with db.session_scope() as s:
        a = s.query(AuditLog).one()
    assert (a.actor, a.role, a.action, a.target, a.outcome) == (
        "operador@contoso.com", "operador", "hallazgo.estado", "azure:/x", "ok")
    assert a.detail["status"] == "asumido"


@pytest.mark.parametrize("ruta,metodo", [
    ("/api/k8s/chat", "post"), ("/api/k8s/incidents", "post"), ("/api/sync", "post"),
    ("/api/integration/test-webhook", "post"),
])
def test_acciones_de_operador(cliente, ruta, metodo):
    r = getattr(cliente, metodo)(ruta, headers=como("lector"), json={})
    assert r.status_code == 403


@pytest.mark.parametrize("ruta", ["/api/admin/database", "/api/admin/audit"])
def test_administracion_solo_para_administradores(cliente, ruta):
    assert cliente.get(ruta, headers=como("operador")).status_code == 403
    assert cliente.get(ruta, headers=como("admin")).status_code == 200


def test_el_admin_ve_la_auditoria(cliente):
    cliente.post("/api/findings/1/status", headers=como("operador"), json={"status": "asumido"})
    items = cliente.get("/api/admin/audit", headers=como("admin")).json()["items"]
    assert [i["action"] for i in items] == ["hallazgo.estado"]


def test_sin_autenticacion_todo_es_administrador(cliente, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    yo = cliente.get("/api/me").json()
    assert yo["role"] == "administrador" and yo["auth_enabled"] is False

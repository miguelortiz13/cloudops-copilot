"""
Cuentas conectadas (Administración): permisos efectivos según lo que el
recolector logró leer, con el proveedor en memoria (cumple el mismo contrato
que Azure, tests/contract).
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.collectors import costs, findings, inventory, run  # noqa: E402
from app.collectors.common import Contexto  # noqa: E402
from app.core import config  # noqa: E402
from app.db import engine as db  # noqa: E402
from app.db.models import Account, Base, CollectorRun  # noqa: E402
from app.providers.base import Capacidad  # noqa: E402
from app.readmodel.cuentas import cuentas_conectadas  # noqa: E402
from tests.contract.proveedores import FabricaMemoria  # noqa: E402

DIA = datetime(2026, 10, 8, 6, 0, tzinfo=timezone.utc)
A, B = "memoria:acct/a", "memoria:acct/b"


@pytest.fixture(autouse=True)
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'c.db'}")
    monkeypatch.setattr(config, "AZURE_MANAGED_IDENTITY_CLIENT_ID", "")
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    yield
    db.reset_engine()


def recolectar(proveedor, momento=DIA, cuentas=None):
    ctx = Contexto(azure=None, inventory=None, cost=None, secops=None, momento=momento, proveedor=proveedor,
                   cuentas=cuentas if cuentas is not None else proveedor.cuentas())
    for nombre, modulo in (("inventory", inventory), ("costs", costs), ("findings", findings)):
        run.ejecutar(nombre, modulo.recolectar, ctx)


def vista():
    with db.session_scope() as s:
        return cuentas_conectadas(s)


def test_permisos_efectivos_por_cuenta():
    recolectar(FabricaMemoria().normal())
    v = vista()
    cuentas = {c["uid"]: c for c in v["accounts"]}
    assert cuentas[A]["cost_status"] == "con_permiso" and cuentas[A]["cost_30d"] == 1.6
    # La cuenta b no entregó costos: le falta el permiso, no "gastó cero".
    assert cuentas[B]["cost_status"] == "sin_permiso" and cuentas[B]["cost_30d"] is None
    assert (cuentas[A]["resources"], cuentas[A]["open_findings"]) == (2, 1)
    assert cuentas[B]["parent"] == "memoria:org/1"
    assert all(c["visible"] for c in v["accounts"])

    (p,) = v["providers"]
    assert p["name"] == "memoria" and p["accounts"] == 2 and p["visible"] == 2 and p["cost_denied"] == 1
    assert p["capabilities"] == {c.value: True for c in Capacidad}
    assert p["unavailable"] == {}


def test_una_cuenta_que_deja_de_verse_pierde_el_acceso():
    proveedor = FabricaMemoria().normal()
    recolectar(proveedor)
    # Al día siguiente la identidad ya no ve la cuenta b.
    proveedor.lista_cuentas = [c for c in proveedor.lista_cuentas if c.uid == A]
    recolectar(proveedor, DIA + timedelta(days=1))
    cuentas = {c["uid"]: c for c in vista()["accounts"]}
    assert cuentas[A]["visible"] is True
    assert cuentas[B]["visible"] is False and cuentas[B]["last_seen"].startswith("2026-10-08")


def test_capacidades_que_faltan_con_su_motivo():
    proveedor = FabricaMemoria().normal()
    proveedor.soporta = frozenset(set(Capacidad) - {Capacidad.IAC})
    proveedor.actividad = None  # soportada pero sin datos
    recolectar(proveedor)
    (p,) = vista()["providers"]
    assert p["capabilities"]["iac"] is False and p["capabilities"]["actividad"] is True
    assert "no soporta iac" in p["unavailable"]["iac"]
    assert "no disponible" in p["unavailable"]["actividad"]


def test_ejecuciones_anteriores_con_ids_nativos():
    """Antes de la capa de proveedores, el detalle de costos guardaba ids de suscripción."""
    with db.session_scope() as s:
        s.add(Account(uid="azure:sub/abc", provider="azure", native_id="abc", name="Vieja", first_seen=DIA, last_seen=DIA))
        s.add(Account(uid="azure:sub/def", provider="azure", native_id="def", name="Con permiso", first_seen=DIA, last_seen=DIA))
        s.add(CollectorRun(collector="costs", started_at=DIA, finished_at=DIA, status="parcial", items=1,
                           detail={"covered": 1, "denied": ["abc"], "failed": []}))
    cuentas = {c["uid"]: c for c in vista()["accounts"]}
    assert cuentas["azure:sub/abc"]["cost_status"] == "sin_permiso"
    assert cuentas["azure:sub/def"]["cost_status"] == "con_permiso"
    # Sin inventario registrado no se afirma que se vean.
    assert not any(c["visible"] for c in cuentas.values())


def test_identidad_de_la_plataforma(monkeypatch):
    recolectar(FabricaMemoria().normal())
    with db.session_scope() as s:
        s.add(Account(uid="azure:sub/x", provider="azure", native_id="x", name="Azure", first_seen=DIA, last_seen=DIA))
    monkeypatch.setattr(config, "AZURE_MANAGED_IDENTITY_CLIENT_ID", "11111111-2222-3333-4444-555555555555")
    azure = next(p for p in vista()["providers"] if p["name"] == "azure")
    assert azure["identity"] == {"kind": "identidad_administrada", "client_id": "11111111-2222-3333-4444-555555555555"}
    assert azure["cost_role"] == "Cost Management Reader" and azure["label"] == "Microsoft Azure"
    # Las capacidades son las del proveedor que corrió, no se atribuyen a otro.
    assert azure["capabilities"] is None


def test_endpoint():
    from app.main import app

    recolectar(FabricaMemoria().normal())
    r = TestClient(app).get("/api/admin/accounts")
    assert r.status_code == 200 and len(r.json()["accounts"]) == 2


def test_endpoint_sin_base(monkeypatch):
    from app.main import app

    for nombre in ("DATABASE_URL", "DB_SERVER", "DB_NAME"):
        monkeypatch.setattr(config, nombre, "")
    assert TestClient(app).get("/api/admin/accounts").json() == {"configured": False, "providers": [], "accounts": []}

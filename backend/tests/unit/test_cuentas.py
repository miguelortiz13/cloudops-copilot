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


def test_una_cuenta_cubierta_sin_filas_gasto_cero():
    """Con permiso de costos y sin filas, el gasto es cero; sin permiso, es desconocido."""
    proveedor = FabricaMemoria().normal()
    proveedor.filas_costo = [f for f in proveedor.filas_costo if f.account_uid != A]
    recolectar(proveedor)
    cuentas = {c["uid"]: c for c in vista()["accounts"]}
    assert (cuentas[A]["cost_status"], cuentas[A]["cost_30d"]) == ("con_permiso", 0.0)
    assert (cuentas[B]["cost_status"], cuentas[B]["cost_30d"]) == ("sin_permiso", None)


def test_aws_con_su_propia_ejecucion_de_inventario(monkeypatch):
    """Fase 2: AWS corre su inventario aparte; cada nube se ve con su corrida y su identidad."""
    from app.collectors import classification
    from app.db.models import AssetClassification
    from app.providers.aws.provider import AwsProvider
    from tests.contract.proveedores import FabricaAws

    recolectar(FabricaMemoria().normal())
    aws = FabricaAws().normal()
    aws.identidad = {"kind": "federacion_oidc", "client_id": None, "role_arn": "arn:aws:iam::111111111111:role/lector"}
    monkeypatch.setattr(AwsProvider, "desde_entorno", classmethod(lambda cls: aws))
    ctx = Contexto(azure=None, inventory=None, cost=None, secops=None, momento=DIA, subscription_ids=[])
    assert run.ejecutar("inventory_aws", run.inventario_aws, ctx) == "ok"
    assert run.ejecutar("classification", classification.recolectar, ctx) == "ok"

    v = vista()
    proveedores = {p["name"]: p for p in v["providers"]}
    assert set(proveedores) == {"memoria", "aws"}
    assert proveedores["aws"]["visible"] == 2 and proveedores["aws"]["identity"]["kind"] == "federacion_oidc"
    assert proveedores["aws"]["capabilities"]["inventario"] and not proveedores["aws"]["capabilities"]["costos"]
    # La corrida de AWS no le quita la visibilidad a las cuentas de la otra nube.
    assert all(c["visible"] for c in v["accounts"])
    cuentas = {c["uid"]: c for c in v["accounts"]}
    assert cuentas["aws:account/111111111111"]["resources"] == 3
    assert cuentas["aws:account/111111111111"]["cost_status"] == "sin_dato"

    # La clasificación ISO cubre los recursos de las dos nubes.
    with db.session_scope() as s:
        clases = {c.resource_uid: c.classification for c in s.query(AssetClassification)}
    assert clases["aws:arn:aws:s3:::lab-datos"] == "Confidencial"
    assert "memoria:res/a/vault-1" in clases


def test_reporte_de_inventario_multinube(monkeypatch, tmp_path):
    """Reportes: inventario de todas las nubes, precalculado por el recolector."""
    from app.collectors import classification
    from app.main import app
    from app.providers.aws.provider import AwsProvider
    from app.readmodel import service
    from tests.contract.proveedores import FabricaAws

    from app.providers.base import Cuenta

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    memoria = FabricaMemoria().normal()
    # Una suscripción visible y vacía también se reporta.
    memoria.lista_cuentas.append(Cuenta("memoria:acct/c", "memoria", "c", "Vacía"))
    recolectar(memoria)
    monkeypatch.setattr(AwsProvider, "desde_entorno", classmethod(lambda cls: FabricaAws().normal()))
    ctx = Contexto(azure=None, inventory=None, cost=None, secops=None, momento=DIA, subscription_ids=[])
    run.ejecutar("inventory_aws", run.inventario_aws, ctx)
    run.ejecutar("classification", classification.recolectar, ctx)
    run.ejecutar("readmodel", run.precalcular_vistas, ctx)

    r = service.inventario_multinube()
    assert r["source"] == "cache", "lo deja listo el recolector: abrir Reportes no despierta la base"
    nubes = {p["name"]: p for p in r["providers"]}
    assert (nubes["memoria"]["resources"], nubes["memoria"]["cost_30d"], nubes["memoria"]["open_findings"]) == (3, 1.6, 2)
    # AWS todavía no entrega costos: desconocido, no cero.
    assert (nubes["aws"]["resources"], nubes["aws"]["cost_30d"], nubes["aws"]["iac_known"]) == (4, None, False)
    assert {"key": "storage.bucket", "count": 1} in nubes["aws"]["by_type"]
    assert {"key": "global", "count": 1} in nubes["aws"]["by_region"]
    boveda = next(x for x in r["resources"] if x["uid"] == "memoria:res/a/vault-1")
    assert (boveda["cost_30d"], boveda["account"], boveda["in_iac"]) == (1.5, "Cuenta A", True)
    assert next(x for x in r["resources"] if x["uid"] == "aws:arn:aws:s3:::lab-datos")["classification"] == "Confidencial"
    por_cuenta = {c["uid"]: c for c in r["accounts"]}
    # Con permiso de costos y sin cargos: cero. Sin permiso: desconocido.
    assert (por_cuenta["memoria:acct/c"]["resources"], por_cuenta["memoria:acct/c"]["cost_30d"]) == (0, 0.0)
    assert por_cuenta[B]["cost_30d"] is None
    assert service.cuentas_conectadas()["source"] == "cache"

    csv = TestClient(app).get("/api/inventory/report/export")
    assert csv.status_code == 200 and "inventario-multinube.csv" in csv.headers["content-disposition"]
    lineas = csv.text.lstrip("﻿").splitlines()
    assert lineas[0].startswith("Nube,Cuenta,Recurso,Tipo") and len(lineas) == 1 + 7
    assert any(line.startswith("aws,Laboratorio,lab-datos,storage.bucket") for line in lineas)

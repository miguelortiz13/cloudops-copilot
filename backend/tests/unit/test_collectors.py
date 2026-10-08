"""
Recolectores contra SQLite con dobles de los servicios: sin Azure.

Lo central es el ciclo de vida de los hallazgos (criterio de salida de la
fase 1: "un hallazgo corregido se marca resuelto solo") y que una consulta
fallida nunca se lea como "ya no hay problema".
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.collectors import costs, findings, inventory, kpis, run  # noqa: E402
from app.collectors.common import Contexto  # noqa: E402
from app.core import config  # noqa: E402
from app.db import engine as db  # noqa: E402
from app.db.models import Base, CollectorRun, CostDaily, Finding, FindingEvent, KpiDaily, Resource  # noqa: E402

SUB = "11111111-1111-1111-1111-111111111111"
RG = f"/subscriptions/{SUB}/resourceGroups/rg"
KV = f"{RG}/providers/Microsoft.KeyVault/vaults/kv1"
NSG = f"{RG}/providers/Microsoft.Network/networkSecurityGroups/nsg1"
DIA = datetime(2026, 10, 8, 6, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'c.db'}")
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    yield
    db.reset_engine()


class SecOps:
    def __init__(self):
        self.findings = []
        self.failed = []

    def build_report(self, subs, strict=False):
        assert strict, "el recolector debe pedir el modo estricto"
        return {"findings": list(self.findings), "failed_queries": list(self.failed)}


class Inventario:
    def __init__(self):
        self.recursos = []
        self.avisos = []

    def _fetch_all_resources(self, subs, force_refresh=False, strict=False):
        assert strict
        return list(self.recursos), list(self.avisos)

    def get_manual_creations(self, subs, limit=100):
        return {"manualCreations": [{"id": KV, "createdBy": "ana@contoso.com"}]}

    def get_summary(self, subs, force_refresh=False):
        return {"tagCompliancePercentage": 87.5, "nonCompliantResources": 4,
                "shadowItCandidates": 2, "resourcesWithoutOwnerCandidate": 1}


class Costos:
    def __init__(self):
        self.filas = []
        self.dias_pedidos = []

    def get_daily_cost_by_resource(self, subs, days=30, pace_seconds=0.0):
        self.dias_pedidos.append(days)
        return {"status": "success", "rows": list(self.filas),
                "coverage": {"covered": [SUB], "denied": [], "failed": []}}


def contexto(momento=DIA, **kw):
    return Contexto(azure=None, inventory=kw.get("inv", Inventario()), cost=kw.get("cost", Costos()),
                    secops=kw.get("sec", SecOps()), subscription_ids=[SUB],
                    subscription_names={SUB: "lab"}, momento=momento)


def correr(modulo, ctx):
    with db.session_scope() as s:
        return modulo.recolectar(ctx, s)


def hallazgo_kv(**extra):
    return {"id": KV, "name": "kv1", "subscriptionId": SUB, "tipo": "keyvault", "severidad": "critica", **extra}


def estados():
    with db.session_scope() as s:
        return {f.resource_uid.rsplit("/", 1)[-1]: f.status for f in s.scalars(select(Finding))}


def eventos():
    with db.session_scope() as s:
        return [e.kind for e in s.scalars(select(FindingEvent).order_by(FindingEvent.id))]


# ---------------------------------------------------------------- hallazgos

def test_ciclo_de_vida_detectado_resuelto_reabierto():
    sec = SecOps()
    sec.findings = [hallazgo_kv()]
    r = correr(findings, contexto(sec=sec))
    assert r.detail["nuevos"] == 1 and estados() == {"kv1": "abierto"}

    # Mismo hallazgo al dia siguiente: no se duplica ni genera eventos.
    correr(findings, contexto(DIA + timedelta(days=1), sec=sec))
    assert eventos() == ["detectado"]

    # Corregido en Azure: deja de aparecer y se resuelve solo.
    sec.findings = []
    r = correr(findings, contexto(DIA + timedelta(days=2), sec=sec))
    assert r.detail["resueltos"] == 1 and estados() == {"kv1": "resuelto"}

    # Vuelve a aparecer: se reabre, no se crea otro.
    sec.findings = [hallazgo_kv()]
    correr(findings, contexto(DIA + timedelta(days=3), sec=sec))
    assert estados() == {"kv1": "abierto"}
    assert eventos() == ["detectado", "resuelto", "reabierto"]
    with db.session_scope() as s:
        assert s.scalar(select(func.count()).select_from(Finding)) == 1


def test_una_consulta_fallida_no_resuelve_nada():
    sec = SecOps()
    sec.findings = [hallazgo_kv()]
    correr(findings, contexto(sec=sec))

    sec.findings, sec.failed = [], ["keyvaults"]
    r = correr(findings, contexto(DIA + timedelta(days=1), sec=sec))
    assert r.status == "parcial"
    assert estados() == {"kv1": "abierto"}


def test_la_aceptacion_vencida_reabre_el_hallazgo():
    sec = SecOps()
    sec.findings = [hallazgo_kv()]
    correr(findings, contexto(sec=sec))
    with db.session_scope() as s:
        f = s.scalars(select(Finding)).one()
        f.status, f.accepted_until = "aceptado", date(2026, 10, 10)

    correr(findings, contexto(datetime(2026, 10, 10, 6, tzinfo=timezone.utc), sec=sec))
    assert estados() == {"kv1": "aceptado"}  # vence al terminar ese dia
    correr(findings, contexto(datetime(2026, 10, 11, 6, tzinfo=timezone.utc), sec=sec))
    assert estados() == {"kv1": "abierto"}
    assert eventos()[-1] == "vencido"


def test_cada_regla_de_un_nsg_es_un_hallazgo():
    sec = SecOps()
    sec.findings = [
        {"id": NSG, "subscriptionId": SUB, "tipo": "nsg", "severidad": "alta", "ruleName": "ssh", "port": "22"},
        {"id": NSG, "subscriptionId": SUB, "tipo": "nsg", "severidad": "alta", "ruleName": "rdp", "port": "3389"},
    ]
    correr(findings, contexto(sec=sec))
    assert estados() == {"ssh": "abierto", "rdp": "abierto"}


# ---------------------------------------------------------------- inventario

def recurso(rid, nombre, tipo="Microsoft.KeyVault/vaults"):
    return {"id": rid, "name": nombre, "type": tipo, "subscriptionId": SUB, "resourceGroup": "rg",
            "location": "eastus2", "tags": {"Environment": "dev"}}


def test_inventario_altas_bajas_y_regreso():
    inv = Inventario()
    otro = f"{RG}/providers/Microsoft.Storage/storageAccounts/st1"
    inv.recursos = [recurso(KV, "kv1"), recurso(otro, "st1", "Microsoft.Storage/storageAccounts")]
    r = correr(inventory, contexto(inv=inv))
    assert r.detail["new"] == 2

    with db.session_scope() as s:
        kv = s.get(Resource, "azure:" + KV.lower())
        assert kv.canonical_type == "secrets.vault"
        assert kv.created_by == "ana@contoso.com"
        assert kv.account_uid == f"azure:sub/{SUB}"

    inv.recursos = [recurso(KV, "kv1")]
    r = correr(inventory, contexto(DIA + timedelta(days=1), inv=inv))
    assert r.detail["deleted"] == 1
    with db.session_scope() as s:
        assert s.get(Resource, "azure:" + otro.lower()).deleted_at is not None

    inv.recursos.append(recurso(otro, "st1", "Microsoft.Storage/storageAccounts"))
    correr(inventory, contexto(DIA + timedelta(days=2), inv=inv))
    with db.session_scope() as s:
        assert s.get(Resource, "azure:" + otro.lower()).deleted_at is None


def test_inventario_incompleto_no_marca_bajas():
    inv = Inventario()
    inv.recursos = [recurso(KV, "kv1")]
    correr(inventory, contexto(inv=inv))

    inv.recursos, inv.avisos = [], ["Throttling detectado en Azure Resource Graph."]
    with pytest.raises(RuntimeError, match="incompleto"):
        correr(inventory, contexto(DIA + timedelta(days=1), inv=inv))
    with db.session_scope() as s:
        assert s.get(Resource, "azure:" + KV.lower()).deleted_at is None


# ---------------------------------------------------------------- costos

def fila_costo(dia, monto, servicio="Key Vault", rid=KV):
    return {"subscription_id": SUB, "date": dia, "resource_id": rid.lower(), "service_name": servicio,
            "cost": monto, "currency": "USD"}


def test_costos_reemplazan_la_ventana_y_luego_usan_siete_dias():
    cost = Costos()
    cost.filas = [fila_costo("2026-10-06", 1.0), fila_costo("2026-10-07", 2.0), fila_costo("2026-10-07", 0.5, "", "")]
    run.ejecutar("costs", costs.recolectar, contexto(cost=cost))

    # Cost Management corrige el dia 7 al dia siguiente: se reemplaza, no se suma.
    cost.filas = [fila_costo("2026-10-06", 1.0), fila_costo("2026-10-07", 3.0), fila_costo("2026-10-07", 0.5, "", "")]
    run.ejecutar("costs", costs.recolectar, contexto(DIA + timedelta(days=1), cost=cost))

    assert cost.dias_pedidos == [costs.DIAS_INICIALES, costs.DIAS_MOVILES]
    with db.session_scope() as s:
        assert s.scalar(select(func.count()).select_from(CostDaily)) == 3
        assert float(s.scalar(select(func.sum(CostDaily.billed_cost)))) == pytest.approx(4.5)
        sin_recurso = s.scalars(select(CostDaily).where(CostDaily.resource_uid == "")).one()
        assert float(sin_recurso.billed_cost) == pytest.approx(0.5)


# ---------------------------------------------------------------- KPIs y ejecucion

def test_kpis_del_dia_son_idempotentes():
    sec = SecOps()
    sec.findings = [hallazgo_kv()]
    inv = Inventario()
    inv.recursos = [recurso(KV, "kv1")]
    correr(inventory, contexto(inv=inv))
    correr(findings, contexto(sec=sec))
    correr(kpis, contexto(inv=inv))
    correr(kpis, contexto(inv=inv))
    with db.session_scope() as s:
        valores = {(k.scope, k.metric): float(k.value) for k in s.scalars(select(KpiDaily))}
    assert valores[("all", "resources_total")] == 1
    assert valores[("all", "findings_open_critica")] == 1
    assert valores[("all", "tag_compliance_pct")] == 87.5
    assert len(valores) == len(set(valores))


def test_un_recolector_que_falla_queda_registrado():
    def roto(ctx, session):
        raise ValueError("Resource Graph devolvio 503")

    assert run.ejecutar("inventory", roto, contexto()) == "error"
    with db.session_scope() as s:
        corrida = s.scalars(select(CollectorRun)).one()
    assert corrida.status == "error" and "503" in corrida.error and corrida.finished_at is not None


def test_el_cliente_estricto_no_confunde_error_con_vacio():
    from app.providers.azure import AzureClient

    cliente = AzureClient(connect=False)
    assert cliente.query_azure_resource_graph("resources") == []
    with pytest.raises(RuntimeError):
        cliente.query_azure_resource_graph("resources", raise_errors=True)

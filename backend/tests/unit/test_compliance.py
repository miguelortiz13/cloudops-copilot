"""
Cumplimiento: catalogo de reglas con mapeo CIS / ISO 27001, estado por control
y clasificacion ISO de activos, contra SQLite.

Lo que importa:
- El catalogo es coherente (cada control citado existe y tiene evidencia).
- Un control nunca se da por cumplido sin evidencia: si la consulta de su
  regla fallo o el recolector no corrio, queda "sin evidencia".
- La clasificacion manual sobrevive al recolector y queda auditada.
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.collectors import classification, findings  # noqa: E402
from app.collectors.common import Contexto  # noqa: E402
from app.providers.azure.provider import AzureProvider  # noqa: E402
from app.compliance import catalog  # noqa: E402
from app.compliance.classification import clasificar, custodio  # noqa: E402
from app.core import config  # noqa: E402
from app.db import engine as db  # noqa: E402
from app.db.models import (  # noqa: E402
    Account, AssetClassification, AuditLog, Base, CollectorRun, Finding, Resource, Rule,
)
from app.readmodel import cumplimiento, service  # noqa: E402

SUB = "11111111-1111-1111-1111-111111111111"
CUENTA = f"azure:sub/{SUB}"
RG = f"/subscriptions/{SUB}/resourcegroups/rg/providers"
KV = f"azure:{RG}/microsoft.keyvault/vaults/kv-prod"
VM = f"azure:{RG}/microsoft.compute/virtualmachines/vm-dev"
ST = f"azure:{RG}/microsoft.storage/storageaccounts/stdev"
T0 = datetime(2026, 10, 8, 6, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'c.db'}")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    with db.session_scope() as s:
        s.add(Account(uid=CUENTA, provider="azure", native_id=SUB, name="Laboratorio", first_seen=T0, last_seen=T0))
        for uid, nombre, tipo, tags, creador in (
            (KV, "kv-prod", "microsoft.keyvault/vaults", {"Environment": "Prod", "Owner": "plataforma"}, None),
            (VM, "vm-dev", "microsoft.compute/virtualmachines", {"environment": "dev"}, "ana@contoso.com"),
            (ST, "stdev", "microsoft.storage/storageaccounts", {}, None),
        ):
            s.add(Resource(uid=uid, provider="azure", account_uid=CUENTA, name=nombre, native_type=tipo,
                           group_name="rg", tags=tags, created_by=creador, first_seen=T0, last_seen=T0))
    yield
    db.reset_engine()


def ctx(momento=T0, secops=None):
    return Contexto(azure=None, inventory=None, cost=None, secops=secops, subscription_ids=[SUB], momento=momento,
                    proveedor=AzureProvider(None, None, secops))


def correr(nombre, detalle=None, estado="ok"):
    with db.session_scope() as s:
        s.add(CollectorRun(collector=nombre, started_at=T0, finished_at=T0, status=estado, items=0, detail=detalle or {}))


def hallazgo(regla, uid, estado="abierto", severidad="alta"):
    with db.session_scope() as s:
        if s.get(Rule, regla) is None:
            r = catalog.POR_ID[regla]
            s.add(Rule(id=r.id, capability="security", title=r.title, severity_default=r.severity_default,
                       frameworks=catalog.frameworks_json(r)))
        s.add(Finding(rule_id=regla, resource_uid=uid, account_uid=CUENTA, severity=severidad, status=estado,
                      details={}, first_seen=T0, last_seen=T0))


def control(vista, marco, cid):
    m = next(f for f in vista["frameworks"] if f["id"] == marco)
    return next(c for c in m["controls"] if c["id"] == cid)


# ---------------------------------------------------------------- catalogo

def test_el_catalogo_es_coherente():
    assert catalog.validar() == []


def test_cada_regla_tiene_detalle_y_al_menos_un_control():
    for r in catalog.REGLAS.values():
        assert r.description and r.detection and r.remediation, r.id
        assert any(r.frameworks.values()), r.id


def test_el_recolector_guarda_el_mapeo_en_la_base():
    class SecOps:
        def build_report(self, subs, strict=False):
            return {"findings": [], "failed_queries": []}

    with db.session_scope() as s:
        findings.recolectar(ctx(secops=SecOps()), s)
    with db.session_scope() as s:
        r = s.get(Rule, "network.admin-port-open")
        assert r.frameworks[catalog.CIS] == [{"control": "6.1", "match": "directa"}, {"control": "6.2", "match": "directa"}]
        assert r.description and r.detection and r.reference_urls


def test_el_reporte_en_vivo_usa_el_catalogo():
    from app.services.secops_service import SecOpsService

    class Azure:
        def query_azure_resource_graph(self, kql, *a, **k):
            return [{"id": "/x/kv", "name": "kv", "sinFirewall": True}] if "keyvault" in kql else []

    h = SecOpsService(Azure()).build_report([])["findings"]
    assert len(h) == 1 and h[0]["regla"] == "secrets.vault-public-network"
    assert h[0]["titulo"] == catalog.REGLAS["keyvault"].title and h[0]["severidad"] == "critica"
    assert h[0]["controles"][catalog.CIS] == [{"control": "8.7", "match": "directa"}]


# ---------------------------------------------------------------- estado de los controles

def test_sin_recoleccion_nada_se_da_por_cumplido():
    with db.session_scope() as s:
        vista = cumplimiento.cumplimiento(s)
    for marco in vista["frameworks"]:
        assert marco["summary"]["cumple"] == 0
        assert marco["summary"]["sin_evidencia"] == marco["controls_evaluated"]


def test_estado_por_control():
    correr("findings")
    hallazgo("secrets.vault-public-network", KV)
    hallazgo("storage.public-blob-access", ST, estado="aceptado")
    hallazgo("network.admin-port-open", VM, estado="resuelto")
    with db.session_scope() as s:
        vista = cumplimiento.cumplimiento(s)

    assert control(vista, catalog.CIS, "8.7")["status"] == "no_cumple"
    assert control(vista, catalog.CIS, "8.7")["active"] == 1
    assert control(vista, catalog.CIS, "3.7")["status"] == "riesgo_aceptado"
    # Un hallazgo resuelto no cuenta en contra.
    assert control(vista, catalog.CIS, "6.1")["status"] == "cumple"
    # A.8.20 lo evidencian varias reglas: manda la peor.
    assert control(vista, catalog.ISO, "A.8.20")["status"] == "no_cumple"
    cis = next(f for f in vista["frameworks"] if f["id"] == catalog.CIS)
    assert sum(cis["summary"].values()) == cis["controls_evaluated"] == 8


def test_una_consulta_fallida_deja_el_control_sin_evidencia():
    correr("findings", {"failed_queries": ["keyvaults"]}, estado="parcial")
    with db.session_scope() as s:
        vista = cumplimiento.cumplimiento(s)
    assert control(vista, catalog.CIS, "8.7")["status"] == "sin_evidencia"
    assert vista["failed_rules"] == ["secrets.vault-public-network"]
    regla = next(r for r in vista["rules"] if r["id"] == "secrets.vault-public-network")
    assert regla["evaluated"] is False


def test_la_evidencia_parcial_se_distingue():
    correr("findings")
    with db.session_scope() as s:
        vista = cumplimiento.cumplimiento(s)
    c = control(vista, catalog.CIS, "4.1.2")
    assert c["direct"] is False and c["evidence"][0]["match"] == "parcial"


# ---------------------------------------------------------------- clasificacion

@pytest.mark.parametrize("tipo,tags,esperado", [
    ("microsoft.keyvault/vaults", {"Environment": "Prod"}, ("Confidencial", 9, True)),
    ("microsoft.sql/servers/databases", {"environment": "production"}, ("Confidencial", 9, True)),
    ("microsoft.web/sites", {"environment": "prd"}, ("Restringido", 8, True)),
    ("microsoft.network/publicipaddresses", {"environment": "prod"}, ("Restringido", 6, True)),
    ("microsoft.storage/storageaccounts", {"environment": "dev"}, ("Restringido", 6, False)),
    ("microsoft.compute/virtualmachines", {}, ("Uso interno", 3, False)),
])
def test_regla_de_clasificacion(tipo, tags, esperado):
    c = clasificar(tipo, tags)
    assert (c.classification, c.score, c.risk_required) == esperado
    assert c.reason


def test_custodio_de_las_tags_o_del_creador():
    assert custodio({"OwnerTech": "redes"}) == "redes"
    assert custodio({"owner": "N/A"}, "ana@contoso.com") == "ana@contoso.com"
    assert custodio({}) is None


def test_el_recolector_clasifica_y_respeta_lo_manual():
    with db.session_scope() as s:
        r = classification.recolectar(ctx(), s)
    assert r.items == 3 and r.detail["nuevas"] == 3
    with db.session_scope() as s:
        kv = s.get(AssetClassification, KV)
        assert (kv.classification, kv.custodian, kv.method) == ("Confidencial", "plataforma", "automatica")
        assert s.get(AssetClassification, VM).custodian == "ana@contoso.com"

    service.clasificar_a_mano(VM, "Restringido", 2, 3, 2, True, "Procesa datos de clientes", None, "luis@contoso.com")
    with db.session_scope() as s:
        s.get(Resource, ST).tags = {"Environment": "Prod"}
        r = classification.recolectar(ctx(), s)
    assert r.detail["manuales"] == 1 and r.detail["cambiadas"] == 1
    with db.session_scope() as s:
        vm = s.get(AssetClassification, VM)
        assert (vm.classification, vm.method, vm.updated_by) == ("Restringido", "manual", "luis@contoso.com")
        assert s.get(AssetClassification, ST).classification == "Confidencial"


def test_restaurar_la_automatica():
    with db.session_scope() as s:
        classification.recolectar(ctx(), s)
    service.clasificar_a_mano(VM, "Confidencial", 3, 3, 3, True, "Datos sensibles", "seguridad", "luis")
    a = service.restaurar_automatica(VM, "luis")
    assert (a["classification"], a["method"], a["custodian"]) == ("Uso interno", "automatica", "ana@contoso.com")


def test_la_clasificacion_manual_exige_motivo():
    with pytest.raises(service.CambioInvalido, match="motivo"):
        service.clasificar_a_mano(VM, "Restringido", 2, 2, 2, False, "  ", None, "luis")
    with pytest.raises(LookupError):
        service.clasificar_a_mano(f"azure:{RG}/no/existe", "Restringido", 2, 2, 2, False, "x", None, "luis")


def test_controles_de_clasificacion():
    with db.session_scope() as s:
        classification.recolectar(ctx(), s)
    correr("classification")
    with db.session_scope() as s:
        vista = cumplimiento.cumplimiento(s)
        activos = cumplimiento.activos(s)
    assert control(vista, catalog.ISO, "A.5.12")["status"] == "cumple"
    # stdev no tiene custodio: el inventario de A.5.9 esta incompleto.
    a59 = control(vista, catalog.ISO, "A.5.9")
    assert a59["status"] == "no_cumple" and a59["active"] == 1
    assert activos["stats"]["classified"] == 3 and activos["stats"]["without_custodian"] == 1
    assert activos["items"][0]["name"] == "kv-prod"


def test_los_hallazgos_activos_se_cuentan_por_activo():
    hallazgo("network.admin-port-open", f"azure:{RG}/microsoft.network/networksecuritygroups/nsg/securityrules/ssh")
    hallazgo("secrets.vault-public-network", KV)
    with db.session_scope() as s:
        activos = cumplimiento.activos(s)
    assert next(a for a in activos["items"] if a["uid"] == KV)["open_findings"] == 1


# ---------------------------------------------------------------- endpoints

def test_endpoints_de_cumplimiento():
    from app.main import app

    with db.session_scope() as s:
        classification.recolectar(ctx(), s)
    cliente = TestClient(app)
    assert {f["id"] for f in cliente.get("/api/compliance").json()["frameworks"]} == {catalog.CIS, catalog.ISO}
    assert cliente.get("/api/compliance/assets").json()["stats"]["total"] == 3

    csv = cliente.get("/api/compliance/assets/export")
    assert csv.headers["content-type"].startswith("text/csv")
    assert csv.text.startswith("﻿Activo,Tipo") and "kv-prod" in csv.text and "Confidencial" in csv.text

    cuerpo = {"resource_uid": VM, "classification": "Restringido", "confidentiality": 2, "integrity": 2,
              "availability": 3, "risk_required": True, "reason": "Expone un servicio interno"}
    r = cliente.post("/api/compliance/assets/classification", json=cuerpo)
    assert r.status_code == 200 and r.json()["method"] == "manual" and r.json()["score"] == 7
    # La vista en cache ya refleja el cambio.
    vm = next(a for a in cliente.get("/api/compliance/assets").json()["items"] if a["uid"] == VM)
    assert vm["classification"] == "Restringido"

    assert cliente.post("/api/compliance/assets/classification", json={**cuerpo, "confidentiality": 4}).status_code == 422
    assert cliente.post("/api/compliance/assets/classification", json={**cuerpo, "reason": " "}).status_code == 400
    assert cliente.post("/api/compliance/assets/classification",
                        json={**cuerpo, "resource_uid": "azure:/no/existe"}).status_code == 404

    r = cliente.post("/api/compliance/assets/classification/restore", json={"resource_uid": VM})
    assert r.json()["method"] == "automatica"
    with db.session_scope() as s:
        acciones = [a.action for a in s.query(AuditLog).order_by(AuditLog.id)]
    assert acciones == ["activo.clasificacion", "activo.clasificacion_automatica"]


def test_el_excel_ya_no_alimenta_el_cumplimiento():
    from app.main import app

    assert TestClient(app).get("/api/governance/iso").status_code == 404

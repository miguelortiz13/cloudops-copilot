"""
Activos (fase 3 del plan 10): la lista multinube y la ficha única de un recurso, con su explicación por la IA.
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import llm  # noqa: E402
from app.core import config, deps  # noqa: E402
from app.db import engine as db  # noqa: E402
from app.db.models import (  # noqa: E402
    Account, AssetClassification, Base, CostDaily, Finding, FindingEvent, Incident, Resource, Rule,
)
from app.llm import limits  # noqa: E402
from app.llm.base import Respuesta  # noqa: E402
from app.main import app  # noqa: E402

T = datetime(2026, 10, 1, tzinfo=timezone.utc)
ST = "azure:/subscriptions/1/resourcegroups/rg/providers/microsoft.storage/storageaccounts/stdatos"
CL = "kubernetes:cluster/lab"


@pytest.fixture(autouse=True)
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'a.db'}")
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    limits.reiniciar()
    with db.session_scope() as s:
        s.add_all([Account(uid="azure:sub/1", provider="azure", native_id="1", name="lab", first_seen=T, last_seen=T),
                   Account(uid=CL, provider="kubernetes", native_id="lab", name="lab", first_seen=T, last_seen=T)])
        s.flush()
        s.add_all([
            Resource(uid=ST, provider="azure", account_uid="azure:sub/1", name="stdatos", canonical_type="storage.account",
                     native_type="microsoft.storage/storageaccounts", region="eastus2", group_name="rg",
                     tags={"environment": "dev"}, in_iac_state=False, created_by="ana@x", first_seen=T, last_seen=T),
            Resource(uid=CL, provider="kubernetes", account_uid=CL, name="lab", canonical_type="kubernetes.cluster",
                     native_type="kubernetes/Cluster", tags={}, first_seen=T, last_seen=T),
            Rule(id="storage.public", capability="storage", title="Blobs públicos", severity_default="alta",
                 remediation="Desactivar el acceso público"),
        ])
        s.flush()
        for d in range(10):
            s.add(CostDaily(charge_date=date(2026, 10, 20) + timedelta(days=d), account_uid="azure:sub/1", resource_uid=ST,
                            service_name="Storage", billed_cost=0.5, effective_cost=0.5, currency="USD", source="query"))
        f = Finding(rule_id="storage.public", resource_uid=ST, account_uid="azure:sub/1", severity="alta", status="abierto",
                    first_seen=T + timedelta(days=1), last_seen=T)
        s.add(f)
        s.flush()
        s.add(FindingEvent(finding_id=f.id, at=T + timedelta(days=1), kind="detectado", actor="recolector"))
        s.add(AssetClassification(resource_uid=ST, classification="Confidencial", confidentiality=3, integrity=2,
                                  availability=1, risk_required=True, custodian="ana@x", method="automatica",
                                  updated_by="recolector", updated_at=T))
        s.add(Incident(key="k", source="alertmanager", cluster="lab", title="PodNotReady · boutique", severity="alta",
                       status="abierto", alerts=[], opened_at=T + timedelta(days=2), last_alert_at=T,
                       diagnosis_status="listo", diagnosis_tools=[]))
    yield
    db.reset_engine()
    llm.reiniciar(None)


@pytest.fixture
def cliente():
    app.dependency_overrides[deps.services] = lambda: SimpleNamespace(azure=SimpleNamespace(azure_credentials=None))
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_ficha_junta_gasto_hallazgos_clasificacion_y_linea_de_tiempo(cliente):
    f = cliente.get("/api/activos/ficha", params={"uid": ST}).json()
    assert (f["name"], f["account"]["name"], f["in_iac"]) == ("stdatos", "lab", False)
    assert f["cost"]["total_30d"] == 5.0 and len(f["cost"]["daily"]) == 10 and f["cost"]["by_service"][0]["service"] == "Storage"
    assert f["findings"][0]["title"] == "Blobs públicos" and f["open_findings"] == 1
    assert f["classification"]["classification"] == "Confidencial"
    assert "Environment" not in f["missing_tags"] and len(f["missing_tags"]) == len(config.MANDATORY_TAGS) - 1
    assert [e["kind"] for e in f["timeline"]] == ["hallazgo.detectado", "recurso.visto"]
    # Un clúster trae sus incidentes.
    c = cliente.get("/api/activos/ficha", params={"uid": CL}).json()
    assert c["cluster"] == "lab" and c["incidents"][0]["title"] == "PodNotReady · boutique"
    assert cliente.get("/api/activos/ficha", params={"uid": "azure:/nada"}).status_code == 404


def test_lista_multinube_filtra_y_ordena_por_gasto(cliente, monkeypatch):
    from app.readmodel import service
    monkeypatch.setattr(service, "inventario_multinube", lambda: {"resources": [
        {"uid": "a", "provider": "aws", "account_uid": "aws:account/1", "name": "bucket", "type": "storage.bucket", "cost_30d": 1, "in_iac": True},
        {"uid": "b", "provider": "azure", "account_uid": "azure:sub/1", "name": "stdatos", "type": "storage.account", "cost_30d": 5, "in_iac": False},
        {"uid": "c", "provider": "azure", "account_uid": "azure:sub/1", "name": "vm1", "type": "compute.vm", "cost_30d": None, "in_iac": None},
    ]})
    r = cliente.get("/api/activos/recursos").json()
    assert [x["uid"] for x in r["items"]] == ["b", "a", "c"] and r["providers"] == ["aws", "azure"]
    assert [x["uid"] for x in cliente.get("/api/activos/recursos?q=storage&en_terraform=false").json()["items"]] == ["b"]
    assert cliente.get("/api/activos/recursos?nube=aws").json()["total"] == 1


def test_la_ia_explica_el_recurso_con_los_datos_de_su_ficha(cliente):
    class Modelo:
        nombre, modelo = "f", "f"

        def generar(self, sistema, mensaje, **k):
            self.mensaje = mensaje
            return Respuesta(texto="**Qué es** una cuenta de almacenamiento", modelo="f")

    assert cliente.post("/api/activos/ficha/explicacion", json={"uid": ST}).status_code == 503  # sin modelo
    modelo = Modelo()
    llm.reiniciar(modelo)
    r = cliente.post("/api/activos/ficha/explicacion", json={"uid": ST}).json()
    assert r["explanation"].startswith("**Qué es**") and "Blobs públicos" in modelo.mensaje and '"total_30d": 5.0' in modelo.mensaje


def test_drift_de_terraform_borrados_fuera_y_tags_cambiadas(cliente, monkeypatch, tmp_path):
    from app.collectors import run
    from app.collectors.common import Contexto
    from app.dominios.activos import drift

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    rg = "/subscriptions/1/resourcegroups/rg/providers"
    indice = {"available": True, "states_read": 2,
              "managed_ids": {f"{rg}/microsoft.storage/storageaccounts/stdatos",           # existe, tags distintas
                              f"{rg}/microsoft.keyvault/vaults/kv-borrado",                # ya no existe: drift
                              f"{rg}/microsoft.network/virtualnetworks/vnet/subnets/sn1",  # hijo: no cuenta
                              f"{rg}/microsoft.authorization/roleassignments/21323cca",    # no está en el inventario
                              "/subscriptions/9/resourcegroups/rg/providers/microsoft.web/sites/otra"},  # otra suscripción
              "tags_by_id": {f"{rg}/microsoft.storage/storageaccounts/stdatos": {"Environment": "prod", "Owner": "plataforma"}},
              "type_by_id": {f"{rg}/microsoft.keyvault/vaults/kv-borrado": "azurerm_key_vault"}}

    class Estados:
        def get_index(self):
            return indice

    ctx = Contexto(azure=None, inventory=None, cost=None, secops=None, subscription_ids=["1"], momento=T,
                   proveedor=SimpleNamespace(_tfstate=Estados()))
    assert run.ejecutar("drift", run._drift, ctx) == "ok"
    d = cliente.get("/api/activos/drift").json()
    assert d["available"] and d["totals"] == {"deleted": 1, "tags": 1}
    assert (d["deleted"][0]["name"], d["deleted"][0]["terraform_type"]) == ("kv-borrado", "azurerm_key_vault")
    cambios = {c["tag"]: (c["terraform"], c["real"]) for c in d["tags"][0]["changes"]}
    assert cambios == {"Environment": ("prod", "dev"), "Owner": ("plataforma", None)}

    # Sin estados configurados: parcial, sin inventar nada.
    ctx.proveedor = SimpleNamespace(_tfstate=None)
    assert run.ejecutar("drift", run._drift, ctx) == "parcial"
    assert drift.leer()["totals"] == {"deleted": 1, "tags": 1}

"""
Lecturas del panel desde la base (app/readmodel) con SQLite y un DATA_DIR
temporal.

Lo que importa ademas de las cifras: una vista precalculada se sirve sin abrir
la base (cada conexion consume cupo gratuito) y las reglas de gestion de
hallazgos no se pueden saltar (aceptar exige fecha y justificacion; "resuelto"
solo lo decide el recolector).
"""

import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import config  # noqa: E402
from app.db import engine as db  # noqa: E402
from app.db.models import Account, Base, CostDaily, Finding, FindingEvent, Resource, Rule  # noqa: E402
from app.readmodel import cache, queries, service  # noqa: E402

CUENTA = "azure:sub/s1"
KV = "azure:/subscriptions/s1/resourcegroups/rg/providers/microsoft.keyvault/vaults/kv1"
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'r.db'}")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    with db.session_scope() as s:
        s.add(Account(uid=CUENTA, provider="azure", native_id="s1", name="Laboratorio", first_seen=T0, last_seen=T0))
        s.add(Resource(uid=KV, provider="azure", account_uid=CUENTA, name="kv1", native_type="microsoft.keyvault/vaults",
                       group_name="rg", tags={}, first_seen=T0, last_seen=T0))
        s.add(Rule(id="secrets.vault-public-network", capability="security", title="Key Vault público",
                   severity_default="alta", frameworks={}))
        # Septiembre: 1 USD/dia en el Key Vault. Octubre 1-8: 2 USD/dia, mas un cargo sin recurso.
        for dia in range(1, 31):
            s.add(_costo(date(2026, 9, dia), 1))
        for dia in range(1, 9):
            s.add(_costo(date(2026, 10, dia), 2))
        s.add(_costo(date(2026, 10, 8), Decimal("0.5"), recurso="", servicio="Support"))
    yield
    db.reset_engine()


def _costo(dia, monto, recurso=KV, servicio="Key Vault"):
    return CostDaily(charge_date=dia, account_uid=CUENTA, resource_uid=recurso, service_name=servicio,
                     billed_cost=Decimal(monto), effective_cost=Decimal(monto), currency="USD", source="query")


def _hallazgo(estado="abierto"):
    with db.session_scope() as s:
        f = Finding(rule_id="secrets.vault-public-network", resource_uid=KV, account_uid=CUENTA, severity="critica",
                    status=estado, details={}, first_seen=T0, last_seen=T0)
        s.add(f)
        s.flush()
        return f.id


# ---------------------------------------------------------------- periodos

def test_periodos():
    hasta = date(2026, 10, 8)
    assert queries.rango("30d", hasta)[:4] == (date(2026, 9, 9), hasta, date(2026, 8, 10), date(2026, 9, 8))
    # Mes en curso contra los mismos dias del mes anterior.
    assert queries.rango("mtd", hasta)[:4] == (date(2026, 10, 1), hasta, date(2026, 9, 1), date(2026, 9, 8))
    assert queries.rango("last_month", hasta)[:4] == (date(2026, 9, 1), date(2026, 9, 30), date(2026, 8, 1), date(2026, 8, 31))
    # 31 de marzo: el mes anterior no tiene dia 31.
    assert queries.rango("mtd", date(2026, 3, 31))[3] == date(2026, 2, 28)
    with pytest.raises(queries.PeriodoInvalido):
        queries.rango("2y", hasta)


# ---------------------------------------------------------------- costos

def test_costos_del_mes_en_curso_contra_el_anterior():
    with db.session_scope() as s:
        c = queries.costos(s, "mtd")
    assert c["total"] == 16.5 and c["previous_total"] == 8.0
    assert c["delta_percentage"] == 106.2
    assert c["previous_complete"] is True
    assert len(c["daily"]) == 8
    assert c["by_resource"][0]["name"] == "kv1" and c["by_resource"][0]["account"] == "Laboratorio"
    assert c["by_resource"][1]["name"] == "Cargos sin recurso"
    assert c["by_account"][0]["name"] == "Laboratorio"
    assert c["by_month"] == [{"month": "2026-09", "cost": 30.0}, {"month": "2026-10", "cost": 16.5}]


def test_comparacion_sin_datos_suficientes_lo_dice():
    with db.session_scope() as s:
        c = queries.costos(s, "last_month")  # el anterior seria agosto, que no esta en la base
    assert c["total"] == 30.0 and c["previous_complete"] is False


def test_sin_costos_no_inventa_cifras():
    with db.session_scope() as s:
        s.query(CostDaily).delete()
    with db.session_scope() as s:
        assert queries.costos(s, "30d")["available"] is False


# ---------------------------------------------------------------- cache

def test_la_vista_precalculada_no_abre_la_base(monkeypatch):
    with db.session_scope() as s:
        service.precalentar(s)

    def prohibido(*a, **k):
        raise AssertionError("abrio la base")

    monkeypatch.setattr(db, "session_scope", prohibido)
    r = service.costos("mtd")
    assert r["source"] == "cache" and r["total"] == 16.5
    assert service.hallazgos()["source"] == "cache"


def test_la_cache_vence_en_la_siguiente_recoleccion():
    def vence(h, m=0):
        return cache.proxima_renovacion(datetime(2026, 10, 8, h, m, tzinfo=timezone.utc))

    # Antes de la corrida de hoy: vale hasta que termine la de hoy.
    assert vence(5) == datetime(2026, 10, 8, 7, 0, tzinfo=timezone.utc)
    # Escrita por el recolector al terminar (06:02): vale hasta mañana, no 58 minutos.
    assert vence(6, 2) == datetime(2026, 10, 9, 7, 0, tzinfo=timezone.utc)
    assert vence(23) == datetime(2026, 10, 9, 7, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- gestion de hallazgos

def test_aceptar_exige_fecha_futura_y_justificacion():
    hid = _hallazgo()
    hoy = date(2026, 10, 8)
    with pytest.raises(service.CambioInvalido, match="vencimiento"):
        service.cambiar_estado(hid, "aceptado", "ana", "porque si", None, None, hoy=hoy)
    with pytest.raises(service.CambioInvalido, match="justificación"):
        service.cambiar_estado(hid, "aceptado", "ana", " ", date(2026, 12, 31), None, hoy=hoy)
    h = service.cambiar_estado(hid, "aceptado", "ana", "Sin VNet en el plan de consumo", date(2026, 12, 31), None, hoy=hoy)
    assert h["status"] == "aceptado" and h["accepted_until"] == "2026-12-31"


def test_asumir_registra_responsable_y_evento():
    hid = _hallazgo()
    h = service.cambiar_estado(hid, "asumido", "ana@contoso.com", None, None, None)
    assert h["owner"] == "ana@contoso.com"
    ev = service.eventos(hid)
    assert ev[-1]["from"] == "abierto" and ev[-1]["to"] == "asumido" and ev[-1]["actor"] == "ana@contoso.com"


def test_un_hallazgo_resuelto_no_se_gestiona_a_mano():
    hid = _hallazgo("resuelto")
    with pytest.raises(service.CambioInvalido):
        service.cambiar_estado(hid, "asumido", "ana", None, None, None)


def test_un_cambio_actualiza_la_vista_en_cache():
    with db.session_scope() as s:
        service.precalentar(s)
    hid = _hallazgo()
    service.cambiar_estado(hid, "asumido", "ana", None, None, None)
    vista = service.hallazgos()
    assert vista["source"] == "cache"
    assert [h["status"] for h in vista["items"]] == ["asumido"]


# ---------------------------------------------------------------- endpoints

def test_endpoints():
    from app.main import app

    cliente = TestClient(app)
    assert cliente.get("/api/history/costs", params={"period": "mtd"}).json()["total"] == 16.5
    assert cliente.get("/api/history/costs", params={"period": "5y"}).status_code == 400
    hid = _hallazgo()
    r = cliente.post(f"/api/findings/{hid}/status", json={"status": "resuelto"})
    assert r.status_code == 422  # no es un estado que se pueda pedir
    r = cliente.post(f"/api/findings/{hid}/status", json={"status": "asumido", "note": "Lo reviso esta semana"})
    assert r.status_code == 200 and r.json()["status"] == "asumido"
    assert cliente.post("/api/findings/999/status", json={"status": "asumido"}).status_code == 404
    with db.session_scope() as s:
        assert s.query(FindingEvent).count() == 1


def test_sin_base_las_vistas_responden_503(monkeypatch):
    from app.main import app

    for nombre in ("DATABASE_URL", "DB_SERVER", "DB_NAME"):
        monkeypatch.setattr(config, nombre, "")
    r = TestClient(app).get("/api/history/costs")
    assert r.status_code == 503


# ---------------------------------------------------------------- tendencia del inventario

def test_la_tendencia_une_la_base_con_el_jsonl():
    from app.services.history_service import fusionar_con_kpis

    jsonl = {"points": [
        {"date": "2026-10-05", "totalResources": 30, "tagCompliancePercentage": 80.0},
        {"date": "2026-10-08", "totalResources": 99},  # la base tiene ese dia: gana la base
    ]}
    kpis = {"metrics": {
        "resources_total": [{"day": "2026-10-08", "value": 35}, {"day": "2026-10-09", "value": 36}],
        "tag_compliance_pct": [{"day": "2026-10-08", "value": 87.5}, {"day": "2026-10-09", "value": 88.0}],
    }}
    r = fusionar_con_kpis(jsonl, kpis)
    assert [p["date"] for p in r["points"]] == ["2026-10-05", "2026-10-08", "2026-10-09"]
    assert r["points"][1]["totalResources"] == 35
    assert r["deltas"] == {"totalResources": 6, "tagCompliancePercentage": 8.0}
    assert r["available"] is True and r["source"] == "kpi_daily+jsonl"


def test_sin_kpis_queda_el_jsonl():
    from app.services.history_service import fusionar_con_kpis

    r = fusionar_con_kpis({"points": [{"date": "2026-10-05", "totalResources": 30}]}, {"metrics": {}})
    assert r["pointCount"] == 1 and r["available"] is False and r["source"] == "jsonl"

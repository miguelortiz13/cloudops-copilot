"""SLOs con presupuesto de error sobre los chequeos HTTP (fase 7.3, plan 12)."""

import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.collectors import chequeos, slo  # noqa: E402
from app.core import ajustes, config, deps  # noqa: E402

URL = "https://tienda.example.com/salud"
INICIO = datetime(2026, 11, 10, 0, tzinfo=timezone.utc)
SANA = {"ok": True, "status": 200, "ms": 40, "error": None}
CAIDA = {"ok": False, "status": 503, "ms": 40, "error": "HTTP 503"}


@pytest.fixture
def publicadas(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setenv("API_URL", "https://api.example")
    monkeypatch.setenv("ALERTS_INGEST_TOKEN", "t0k3n")
    ajustes.guardar("chequeos", {"urls": [URL]})
    salida = []

    class Respuesta:
        def raise_for_status(self):
            pass

    monkeypatch.setattr(chequeos.requests, "post", lambda url, json=None, headers=None, timeout=None: salida.append(json) or Respuesta())
    return salida


def correr(resultados, desde):
    """Un chequeo cada 10 minutos desde `desde` con los resultados dados; devuelve el momento siguiente."""
    for n, r in enumerate(resultados):
        chequeos.ejecutar(desde + timedelta(minutes=10 * n), lambda u, r=r: r)
    return desde + timedelta(minutes=10 * len(resultados))


def test_fallas_intermitentes_queman_el_presupuesto_y_abren_su_incidente(publicadas):
    t = correr([SANA] * 30, INICIO)  # 5 horas sanas
    t = correr([CAIDA, SANA] * 3, t)  # nunca dos seguidas: el chequeo no abre nada
    assert [p["alerts"][0]["labels"]["alertname"] for p in publicadas] == ["SLOBurnRate"]
    alerta = publicadas[0]["alerts"][0]
    assert "quema su presupuesto de error" in alerta["annotations"]["summary"] and "SLO 99.5 %" in alerta["annotations"]["summary"]
    e = slo.estado(t)["items"][0]
    assert e["samples"] == 36 and e["failures"] == 3 and e["availability_pct"] == 91.667 and e["burning"]
    assert e["budget_consumed_pct"] > 100 and e["met"] is False
    correr([SANA] * 6, t)  # una hora sana: se resuelve
    assert [p["status"] for p in publicadas] == ["firing", "resolved"]


def test_con_poca_historia_o_caida_no_duplica(publicadas):
    correr([CAIDA] * 3, INICIO)  # 3 fallas seguidas: solo el incidente del chequeo
    assert [p["alerts"][0]["labels"]["alertname"] for p in publicadas] == ["HttpCheckFailed"]


def test_ruta(publicadas):
    from app.main import app
    correr([SANA] * 10, datetime.now(timezone.utc) - timedelta(hours=2))
    app.dependency_overrides[deps.services] = lambda: SimpleNamespace(azure=SimpleNamespace(azure_credentials=None))
    try:
        r = TestClient(app).get("/api/operacion/slos").json()
        assert r["objective_pct"] == 99.5 and r["window_days"] == 28
        assert r["items"][0]["availability_pct"] == 100.0 and r["items"][0]["budget_remaining_pct"] == 100.0
    finally:
        app.dependency_overrides.clear()

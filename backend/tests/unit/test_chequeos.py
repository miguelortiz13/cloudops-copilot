"""
Chequeos HTTP (fase 4 del plan 10): dos fallas seguidas abren un incidente por la misma ruta que
Alertmanager; al responder se resuelve. Sin acceso a la red interna.
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402

from app.ai import incidentes  # noqa: E402
from app.collectors import chequeos  # noqa: E402
from app.core import ajustes, config  # noqa: E402
from app.db import engine as db  # noqa: E402
from app.db.models import Base, Incident  # noqa: E402

AHORA = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
URL = "https://tienda.example.com/salud"


@pytest.fixture(autouse=True)
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'c.db'}")
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    yield
    db.reset_engine()


def test_dos_fallas_abren_un_incidente_y_la_respuesta_lo_resuelve(monkeypatch):
    monkeypatch.setenv("API_URL", "https://api.example")
    monkeypatch.setenv("ALERTS_INGEST_TOKEN", "t0k3n")
    ajustes.guardar("chequeos", {"urls": [URL]})
    publicadas = []

    class Respuesta:
        def raise_for_status(self):
            pass

    def post(url, json=None, headers=None, timeout=None):
        assert url == "https://api.example/api/alerts/alertmanager" and headers["Authorization"] == "Bearer t0k3n"
        publicadas.append(json)
        incidentes.ingresar_alertmanager(json, None, AHORA)  # lo que haría el API
        return Respuesta()

    monkeypatch.setattr(chequeos.requests, "post", post)
    caida = lambda u: {"ok": False, "status": 503, "ms": 40, "error": "HTTP 503"}  # noqa: E731
    sana = lambda u: {"ok": True, "status": 200, "ms": 40, "error": None}  # noqa: E731

    chequeos.ejecutar(AHORA, caida)
    assert publicadas == []  # una sola falla no abre nada
    chequeos.ejecutar(AHORA, caida)
    chequeos.ejecutar(AHORA, caida)  # sigue caída: no se repite
    assert [p["status"] for p in publicadas] == ["firing"]
    with db.session_scope() as s:
        i = s.query(Incident).one()
        assert i.status == "abierto" and i.title.startswith("HttpCheckFailed") and i.severity == "critica"
    chequeos.ejecutar(AHORA, sana)
    assert [p["status"] for p in publicadas] == ["firing", "resolved"]
    with db.session_scope() as s:
        assert s.query(Incident).one().status == "resuelto"
    assert chequeos.leer_estado()[URL]["abierta"] is False


def test_si_no_se_pudo_publicar_lo_intenta_de_nuevo(monkeypatch):
    monkeypatch.setenv("API_URL", "https://api.example")
    monkeypatch.setenv("ALERTS_INGEST_TOKEN", "t0k3n")
    ajustes.guardar("chequeos", {"urls": [URL]})

    def falla(*a, **k):
        raise chequeos.requests.ConnectionError()

    monkeypatch.setattr(chequeos.requests, "post", falla)
    caida = lambda u: {"ok": False, "status": None, "ms": None, "error": "ConnectTimeout"}  # noqa: E731
    chequeos.ejecutar(AHORA, caida)
    chequeos.ejecutar(AHORA, caida)
    assert chequeos.leer_estado()[URL]["abierta"] is False  # sin publicar no cuenta como abierta


def test_no_revisa_direcciones_privadas_ni_de_metadatos():
    for host in ("127.0.0.1", "169.254.169.254", "10.0.0.4", "localhost"):
        assert chequeos.direccion_publica(host) is False
    assert chequeos.revisar("https://169.254.169.254/metadata")["error"].startswith("La URL no resuelve")


def test_solo_urls_https_en_los_ajustes():
    with pytest.raises(ValueError):
        ajustes.guardar("chequeos", {"urls": ["http://inseguro.example"]})
    with pytest.raises(ValueError):
        ajustes.guardar("chequeos", {"urls": ["https://a b.example"]})
    assert ajustes.guardar("chequeos", {"urls": [URL, URL]})["urls"] == [URL]

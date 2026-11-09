"""Reporte mensual por bloques y narrado por la IA (fase 5 del plan 10)."""

import json
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
from app.db.models import Base, Incident  # noqa: E402
from app.llm import limits  # noqa: E402
from app.llm.base import Respuesta  # noqa: E402
from app.reports import mensual  # noqa: E402

MES = date(2026, 10, 1)


class Modelo:
    nombre, modelo = "falso", "falso-1"

    def __init__(self, texto):
        self.texto, self.mensajes = texto, []

    def generar(self, sistema, mensaje, **k):
        self.mensajes.append((mensaje, k))
        return Respuesta(texto=self.texto, modelo="falso-1")


@pytest.fixture(autouse=True)
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'r.db'}")
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    abierto = datetime(2026, 10, 5, 4, tzinfo=timezone.utc)
    with db.session_scope() as s:
        s.add_all([Incident(id=n, key=f"k{n}", source="alertmanager", cluster="lab", title=f"PodCrashLooping {n}", severity=sev,
                            status="resuelto", alerts=[], opened_at=abierto, last_alert_at=abierto,
                            resolved_at=abierto + timedelta(minutes=minutos), closed_reason=cierre, feedback=marca)
                   for n, sev, minutos, cierre, marca in [(1, "critica", 23, "solucionado", "correcto"), (2, "media", 7, "ruido", None)]])
    limits.reiniciar()
    yield
    db.reset_engine()
    llm.reiniciar(None)
    limits.reiniciar()


def datos():
    with db.session_scope() as s:
        return mensual.datos(s, MES)


def test_bloques_validos_en_el_orden_del_reporte():
    assert mensual.bloques_de(None) == mensual.BLOQUES
    assert mensual.bloques_de("incidentes, costos") == ("costos", "incidentes")
    with pytest.raises(ValueError, match="clima"):
        mensual.bloques_de("costos,clima")


def test_el_pdf_trae_solo_los_bloques_pedidos_y_la_seccion_de_incidentes():
    d = datos()
    assert d["incidentes"]["total"] == 2 and d["incidentes"]["mediana_min"] == 23 and d["incidentes"]["ruido"] == 1
    pdf = mensual.pdf(d, date(2026, 11, 4), ("incidentes",))
    assert b"(Incidentes del mes: 2)" in pdf and b"(Costos)" not in pdf and b"(Seguridad)" not in pdf
    assert b"mediana para resolver: 23 min" in pdf


def test_la_narracion_usa_solo_los_bloques_pedidos_y_va_en_el_pdf():
    m = Modelo(json.dumps({"incidentes": "Hubo 2 incidentes; uno se cerró como ruido. " * 6, "costos": "no pedido"}))
    llm.reiniciar(m)
    d = datos()
    n = mensual.narrar(d, ("incidentes",), "ana@x")
    assert set(n) == {"incidentes"} and m.mensajes[0][1]["json"] is True
    mensaje = m.mensajes[0][0]
    assert "<<<DATOS_NO_CONFIABLES>>>" in mensaje and '"incidentes"' in mensaje and '"costos"' not in mensaje
    pdf = mensual.pdf(d, date(2026, 11, 4), ("incidentes",), n)
    assert b"(Hubo 2 incidentes; uno se cerr" in pdf and b"redact\xf3 la IA" in pdf
    m.texto = "esto no es JSON"
    assert mensual.narrar(d, ("incidentes",), "ana@x") == {}  # sin narración, el reporte sale igual


def test_la_ruta_valida_bloques_y_narra_si_hay_modelo():
    from app.main import app
    app.dependency_overrides[deps.services] = lambda: SimpleNamespace(azure=SimpleNamespace(azure_credentials=None))
    try:
        c = TestClient(app)
        assert c.get("/api/reports/monthly", params={"month": "2026-10", "bloques": "clima"}).status_code == 422
        assert c.get("/api/reports/monthly", params={"month": "2026-10", "narrar": True}).status_code == 503
        llm.reiniciar(Modelo(json.dumps({"costos": "Sin gasto registrado en octubre.", "incidentes": "Dos incidentes."})))
        r = c.get("/api/reports/monthly", params={"month": "2026-10", "bloques": "costos,incidentes", "narrar": True})
        assert r.status_code == 200 and b"(Sin gasto registrado en octubre.)" in r.content and b"(Inventario)" not in r.content
    finally:
        app.dependency_overrides.clear()

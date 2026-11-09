"""
Motor de avisos (fase 2 del plan 10): silencios, duplicados, modo registro y activo, el
registro de envíos y su ruta del API.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import ajustes, avisos, config  # noqa: E402

DISCORD = "https://discord.com/api/webhooks/1/SECRETO"
AHORA = datetime.now(timezone.utc)
MENSAJE = {"titulo": "Kubernetes · lab", "lineas": ["- [critica] CrashLoopBackOff: web-1"], "enlace": "https://panel/#/x"}


@pytest.fixture
def canal(monkeypatch, tmp_path):
    from app.collectors import notify
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    enviados = []

    def post(url, json=None, timeout=None, data=None, files=None):
        enviados.append({"json": json, "data": data, "files": files})
        return SimpleNamespace(status_code=500 if "falla" in url else 204)

    monkeypatch.setattr(notify.requests, "post", post)
    return enviados


def publicar(clave="k8s:lab:1", cuando=AHORA, **kw):
    return avisos.publicar(kw.pop("url", DISCORD), MENSAJE, dominio="activos", tipo="kubernetes", severidad="critica",
                           clave=clave, atributos={"cluster": "lab", "objetos": ["web-1"]}, ahora=cuando, **kw)


def test_en_modo_registro_envia_todo_y_anota_lo_que_habria_silenciado(canal):
    ajustes.silenciar("ana@x", 1, "mantenimiento", cluster="lab")
    assert publicar() == "enviado" and publicar() == "enviado"
    assert len(canal) == 2
    decisiones = [(e["decision"], e["enviado"], e["modo"]) for e in avisos.registro()]
    assert decisiones == [("silenciado", True, "registro")] * 2


def test_en_modo_activo_respeta_silencios_y_descarta_duplicados(canal):
    ajustes.guardar("avisos", {"modo": "activo", "deduplicar_min": 10})
    assert publicar() == "enviado"
    assert publicar(cuando=AHORA + timedelta(minutes=5)) == "duplicado"
    assert publicar(cuando=AHORA + timedelta(minutes=11)) == "enviado"  # fuera de la ventana
    s = ajustes.silenciar("ana@x", 1, "mantenimiento", cluster="lab", objeto="web")
    assert publicar(clave="otra", cuando=AHORA + timedelta(minutes=12)) == "silenciado"
    assert len(canal) == 2
    assert avisos.registro(ahora=AHORA + timedelta(minutes=13))[0]["silencio"] == s["id"]


def test_una_falla_del_canal_queda_registrada_y_se_propaga(canal):
    with pytest.raises(RuntimeError):
        publicar(url="https://discord.com/api/webhooks/falla/x")
    e = avisos.registro()[0]
    assert e["enviado"] is False and "500" in e["error"] and e["canal"] == "discord.com"
    assert "SECRETO" not in str(e)  # la URL es una credencial: solo el host


def test_el_adjunto_solo_va_a_discord(canal):
    avisos.publicar(DISCORD, MENSAJE, dominio="plataforma", tipo="reporte_mensual", severidad="info", clave="r1",
                    adjunto=("r.pdf", b"%PDF", "application/pdf"))
    avisos.publicar("https://hooks.slack.com/services/x", MENSAJE, dominio="plataforma", tipo="reporte_mensual",
                    severidad="info", clave="r2", adjunto=("r.pdf", b"%PDF", "application/pdf"))
    assert canal[0]["files"]["files[0]"][0] == "r.pdf" and canal[1]["files"] is None and canal[1]["json"]["text"]


def test_ruta_del_registro(canal):
    from app.core import deps
    from app.main import app
    publicar()
    app.dependency_overrides[deps.services] = lambda: SimpleNamespace(azure=SimpleNamespace(azure_credentials=None))
    try:
        r = TestClient(app).get("/api/notifications?dias=7").json()
    finally:
        app.dependency_overrides.clear()
    assert r["mode"] == "registro" and r["items"][0]["tipo"] == "kubernetes"
    assert r["stats"] == {"total": 1, "enviados": 1, "silenciados": 0, "duplicados": 0, "filtrados": 0, "fallidos": 0}


def test_severidad_minima_por_dominio_y_silencio_por_tipo_de_aviso(canal):
    ajustes.guardar("avisos", {"modo": "activo", "minimo_activos": "critica"})
    assert avisos.publicar(DISCORD, MENSAJE, dominio="activos", tipo="kubernetes", severidad="alta", clave="a1") == "filtrado"
    assert publicar(clave="a2") == "enviado"  # crítica: pasa
    # Silenciar un tipo de aviso entero (el resumen semanal) desde Operación → Silencios.
    ajustes.silenciar("ana@x", 24, "vacaciones del equipo", alerta="resumen_semanal")
    assert avisos.publicar(DISCORD, MENSAJE, dominio="inicio", tipo="resumen_semanal", severidad="info", clave="s1") == "silenciado"
    assert avisos.publicar(DISCORD, MENSAJE, dominio="inicio", tipo="otro", severidad="info", clave="s2") == "enviado"
    assert len(canal) == 2


def test_al_canal_solo_salen_enlaces_del_panel(canal, monkeypatch):
    """IA-2: aunque el texto venga del modelo (diagnóstico, resumen), no se publica un enlace ajeno."""
    monkeypatch.setattr(config, "FRONTEND_URL", "https://panel.example")
    m = {"titulo": "Incidente", "enlace": "https://evil.example/login",
         "lineas": ["Ver [la causa](https://panel.example/#/operacion/incidentes/1) y [entra aquí](https://evil.example/x)",
                    "o https://evil.example/y"]}
    avisos.publicar(DISCORD, m, dominio="operacion", tipo="incidente", severidad="alta", clave="i1")
    embed = canal[0]["json"]["embeds"][0]
    assert embed["url"] == "https://panel.example"
    assert embed["description"] == ("Ver [la causa](https://panel.example/#/operacion/incidentes/1) y entra aquí\n"
                                    "o [enlace quitado]")

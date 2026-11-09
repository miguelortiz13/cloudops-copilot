"""Servidor MCP (plan 11, hito IA-3): tokens, protocolo, autenticación, auditoría y trazas."""

import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import config, deps, trazas  # noqa: E402
from app.dominios.plataforma import mcp  # noqa: E402
from app.services import auth  # noqa: E402


@pytest.fixture
def cliente(monkeypatch, tmp_path):
    from app.ai import herramientas
    from app.main import app

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    mcp._uso.clear()
    auditados = []
    monkeypatch.setattr(mcp, "auditar", lambda u, accion, objetivo=None, detalle=None, resultado="ok":
                        auditados.append((u.actor, accion, objetivo, resultado)))
    hallazgos = lambda severidad=None, **_: {"total": 2, "severidad": severidad, "enlace": "#/riesgo/hallazgos"}  # noqa: E731
    reales = herramientas.para_asistente

    def para_asistente(cred):
        hs = reales(cred)
        for h in hs:
            if h.nombre == "hallazgos":
                h.funcion = hallazgos
        return hs

    monkeypatch.setattr(herramientas, "para_asistente", para_asistente)
    app.dependency_overrides[deps.services] = lambda: SimpleNamespace(azure=SimpleNamespace(azure_credentials=None))
    c = TestClient(app)
    c.auditados = auditados
    yield c
    app.dependency_overrides.clear()


def rpc(c, metodo, params=None, token=None, id_=1, headers=None):
    msg = {"jsonrpc": "2.0", "method": metodo, **({"params": params} if params is not None else {}), **({"id": id_} if id_ else {})}
    return c.post("/mcp", json=msg, headers={**(headers or {}), **({"Authorization": f"Bearer {token}"} if token else {})})


def test_tokens_se_guardan_con_hash_vencen_y_se_revocan(cliente, tmp_path):
    ahora = datetime.now(timezone.utc)
    t = mcp.emitir("claude-code", 30, "ana@x", ahora)
    assert t["token"].startswith("cop_mcp_") and t["token"] not in (tmp_path / "mcp" / "tokens.json").read_text()
    assert mcp.validar(t["token"], ahora)["id"] == t["id"]
    assert mcp.validar(t["token"], ahora + timedelta(days=31)) is None  # vencido
    assert mcp.validar("cop_mcp_otro", ahora) is None
    assert mcp.revocar(t["id"], "ana@x") and mcp.validar(t["token"], ahora) is None
    assert not mcp.revocar(t["id"], "ana@x")


def test_sin_token_valido_no_entra(cliente):
    assert rpc(cliente, "tools/list").status_code == 401
    assert rpc(cliente, "tools/list", token="cop_mcp_falso").status_code == 401
    assert cliente.get("/mcp").status_code == 405


def test_protocolo_y_herramientas_con_auditoria_y_traza(cliente):
    token = mcp.emitir("claude-code", 30, "ana@x")["token"]
    r = rpc(cliente, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}, token).json()
    assert r["result"]["protocolVersion"] == "2025-06-18" and "tools" in r["result"]["capabilities"]
    assert rpc(cliente, "notifications/initialized", token=token, id_=None).status_code == 202

    nombres = {h["name"] for h in rpc(cliente, "tools/list", token=token).json()["result"]["tools"]}
    assert {"buscar_recursos", "costos", "hallazgos", "incidentes", "incidente", "estado_cluster"} <= nombres

    r = rpc(cliente, "tools/call", {"name": "hallazgos", "arguments": {"severidad": "critica"}}, token).json()["result"]
    assert r["isError"] is False and '"datos_no_confiables"' in r["content"][0]["text"] and '"total": 2' in r["content"][0]["text"]
    r = rpc(cliente, "tools/call", {"name": "hallazgos", "arguments": {"severidad": "todas"}}, token).json()["result"]
    assert r["isError"] is True and "Argumento inválido" in r["content"][0]["text"]  # mismas guardas que el chat
    assert rpc(cliente, "resources/list", token=token).json()["error"]["code"] == -32601

    assert [(a[1], a[2], a[3]) for a in cliente.auditados] == [("mcp.herramienta", "hallazgos", "ok"), ("mcp.herramienta", "hallazgos", "error")]
    assert cliente.auditados[0][0].startswith("mcp:") and "ana@x" in cliente.auditados[0][0]
    t = trazas.leer(1)
    assert {x["attributes"]["cloudops.use"] for x in t} == {"mcp.hallazgos"}
    resumen = trazas.resumen(t, 0, 0)
    assert resumen["total"]["calls"] == 0 and resumen["mcp"]["calls"] == 2 and resumen["mcp"]["errors"] == 1


def test_origen_ajeno_y_cupo_por_token(cliente, monkeypatch):
    token = mcp.emitir("x", 1, "ana@x")["token"]
    assert rpc(cliente, "ping", token=token, headers={"Origin": "https://evil.example"}).status_code == 403
    monkeypatch.setattr(mcp, "MAX_POR_HORA", 1)
    llamar = lambda: rpc(cliente, "tools/call", {"name": "hallazgos", "arguments": {}}, token).json()["result"]  # noqa: E731
    assert llamar()["isError"] is False and "Cupo agotado" in llamar()["content"][0]["text"]


def test_gestion_de_tokens_solo_administrador(cliente, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)  # sin autenticación todos son administradores
    nuevo = cliente.post("/api/ia/mcp/tokens", json={"nombre": "claude-code", "dias": 7}).json()
    assert nuevo["token"].startswith("cop_mcp_")
    items = cliente.get("/api/ia/mcp/tokens").json()["items"]
    assert items[0]["id"] == nuevo["id"] and "hash" not in items[0] and "token" not in items[0]
    assert cliente.delete(f"/api/ia/mcp/tokens/{nuevo['id']}").json() == {"revoked": nuevo["id"]}
    assert cliente.delete(f"/api/ia/mcp/tokens/{nuevo['id']}").status_code == 404
    assert [a[1] for a in cliente.auditados] == ["mcp.token.emitir", "mcp.token.revocar"]

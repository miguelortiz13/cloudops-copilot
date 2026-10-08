"""
Capa de modelos de lenguaje (app/llm) sin red.

- Gemini sobre google-genai: se sustituye `genai.Client` y se verifica lo que
  se le pide (instrucciones de sistema, temperatura, modo JSON) y como se
  traducen sus fallas.
- Los tres agentes usan la interfaz y caen al motor de reglas si el modelo
  falla o no esta configurado.
- El limite por usuario: ventanas de hora y dia, 429 con Retry-After.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import llm  # noqa: E402
from app.core import config  # noqa: E402
from app.llm import limits  # noqa: E402
from app.llm.base import LLMError, Respuesta  # noqa: E402


class ProveedorFalso:
    nombre = "falso"
    modelo = "falso-1"

    def __init__(self, texto="respuesta del modelo", error=None):
        self.texto, self.error, self.llamadas = texto, error, []

    def generar(self, sistema, mensaje, temperatura=0.2, json=False, max_tokens=None):
        self.llamadas.append({"sistema": sistema, "mensaje": mensaje, "temperatura": temperatura, "json": json})
        if self.error:
            raise LLMError(self.error)
        return Respuesta(texto=self.texto, modelo=self.modelo, tokens_entrada=10, tokens_salida=5)


@pytest.fixture(autouse=True)
def aislado():
    limits.reiniciar()
    yield
    llm.reiniciar(None)
    limits.reiniciar()


# ---------------------------------------------------------------- Gemini (google-genai)

class ModelosFalsos:
    def __init__(self, respuesta=None, error=None):
        self.respuesta, self.error, self.pedidos = respuesta, error, []

    def generate_content(self, model, contents, config):
        self.pedidos.append({"model": model, "contents": contents, "config": config})
        if self.error:
            raise self.error
        return self.respuesta


def gemini_con(monkeypatch, respuesta=None, error=None):
    from google import genai

    modelos = ModelosFalsos(respuesta, error)
    monkeypatch.setattr(genai, "Client", lambda **kw: SimpleNamespace(models=modelos))
    from app.llm.gemini import Gemini

    return Gemini("clave-falsa", "gemini-prueba"), modelos


def test_gemini_envia_instrucciones_y_modo_json(monkeypatch):
    uso = SimpleNamespace(prompt_token_count=120, candidates_token_count=40)
    g, modelos = gemini_con(monkeypatch, SimpleNamespace(text=' {"main_tf": "x"} ', usage_metadata=uso, candidates=[]))
    r = g.generar("eres un experto", "genera HCL", temperatura=0.1, json=True)
    assert r.texto == '{"main_tf": "x"}' and (r.tokens_entrada, r.tokens_salida) == (120, 40)
    pedido = modelos.pedidos[0]
    assert pedido["model"] == "gemini-prueba" and pedido["contents"] == "genera HCL"
    assert pedido["config"].system_instruction == "eres un experto"
    assert pedido["config"].temperature == 0.1
    assert pedido["config"].response_mime_type == "application/json"


def test_gemini_traduce_errores(monkeypatch):
    g, _ = gemini_con(monkeypatch, error=RuntimeError("429 RESOURCE_EXHAUSTED"))
    with pytest.raises(LLMError, match="RESOURCE_EXHAUSTED"):
        g.generar("s", "m")


def test_gemini_respuesta_vacia_es_error(monkeypatch):
    g, _ = gemini_con(monkeypatch, SimpleNamespace(text="", usage_metadata=None, candidates=[SimpleNamespace(finish_reason="SAFETY")]))
    with pytest.raises(LLMError, match="SAFETY"):
        g.generar("s", "m")


def test_sin_clave_no_hay_modelo(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    llm._iniciado = False
    assert llm.disponible() is False
    with pytest.raises(LLMError):
        llm.generar("x", "s", "m")


def test_proveedor_none_desactiva_el_modelo_aunque_haya_clave(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "none")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "una-clave")
    llm._iniciado = False
    assert llm.disponible() is False


def test_generar_registra_el_consumo(capsys):
    llm.reiniciar(ProveedorFalso())
    llm.generar("chat.finops", "s", "m", usuario="ana@contoso.com")
    linea = [l for l in capsys.readouterr().out.splitlines() if l.startswith("[llm]")][-1]
    assert '"uso": "chat.finops"' in linea and '"tokens_entrada": 10' in linea and "ana@contoso.com" in linea


# ---------------------------------------------------------------- agentes

def agente():
    from app.agents.azure_agent import AzureInventoryAgent
    from app.providers.azure import AzureClient

    return AzureInventoryAgent(AzureClient(connect=False))


def test_el_chat_usa_el_modelo_y_cae_a_reglas_si_falla():
    falso = ProveedorFalso("Tienes 3 discos huérfanos.")
    llm.reiniciar(falso)
    r = agente().ask("¿qué discos sobran?", agent_type="finops", usuario="ana")
    assert r["answer"] == "Tienes 3 discos huérfanos." and r["mode"] == "llm_falso_finops"
    assert "¿qué discos sobran?" in falso.llamadas[0]["mensaje"]

    llm.reiniciar(ProveedorFalso(error="cuota agotada"))
    r = agente().ask("¿qué discos sobran?", agent_type="finops")
    assert not r["mode"].startswith("llm_")


def test_iac_con_modelo_y_respaldo_de_plantillas():
    from app.agents.iac_generator import IaCManager

    recurso = {"id": "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/st1",
               "name": "st1", "type": "microsoft.storage/storageaccounts", "location": "eastus2",
               "resourceGroup": "rg", "subscriptionId": "s", "tags": {}, "properties": {}, "sku": {"name": "Standard_LRS"}}
    azure = SimpleNamespace(query_azure_resource_graph=lambda *a, **k: [recurso])

    falso = ProveedorFalso('{"main_tf": "resource \\"x\\" \\"y\\" {}", "providers_tf": "", "variables_tf": "", "outputs_tf": "", "terraform_tfvars": "", "backend_hcl": ""}')
    llm.reiniciar(falso)
    r = IaCManager(azure).generate_iac_files(recurso["id"], "dev", "data", usuario="ana")
    assert r["generation_mode"] == "llm_falso" and falso.llamadas[0]["json"] is True

    llm.reiniciar(ProveedorFalso(error="caído"))
    r = IaCManager(azure).generate_iac_files(recurso["id"], "dev", "data")
    assert r["generation_mode"] != "llm_falso" and "st1" in r["main_tf"]


def test_k8s_sin_modelo_responde_con_el_estado_del_cluster():
    from app.services.k8s_service import K8sService

    llm.reiniciar(None)
    s = K8sService.__new__(K8sService)
    s.cluster_name = "aks-lab"
    s.get_incidents = lambda req: {"clusterHealthScore": 92, "summary": {"HIGH": 1, "LOW": 0}}
    s._get_nodes_status = lambda: ([], 3, 3)
    s._get_problem_pods = lambda ns=None: []
    r = s.chat("¿qué pasa?", {})
    assert r["mode"] == "rules" and "92/100" in r["answer"] and "HIGH: 1" in r["answer"]
    assert "GEMINI_API_KEY" not in r["answer"]


# ---------------------------------------------------------------- limite por usuario

@pytest.fixture
def cliente_chat():
    """El API con un agente simulado: el limite se prueba sin tocar Azure."""
    from app.core import deps
    from app.main import app

    agente_falso = SimpleNamespace(ask=lambda *a, **k: {"answer": "ok", "mode": "rules", "data": []})
    app.dependency_overrides[deps.services] = lambda: SimpleNamespace(agent=agente_falso)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_ventanas_de_hora_y_dia(monkeypatch):
    monkeypatch.setattr(config, "LLM_MAX_REQUESTS_PER_HOUR", 2)
    monkeypatch.setattr(config, "LLM_MAX_REQUESTS_PER_DAY", 3)
    t = 1_000_000.0
    limits.consumir("ana", t)
    limits.consumir("ana", t + 10)
    with pytest.raises(limits.LimiteExcedido, match="por hora") as e:
        limits.consumir("ana", t + 20)
    assert e.value.reintentar_en == 3581
    limits.consumir("luis", t + 20)  # cada usuario tiene su cupo
    limits.consumir("ana", t + 3601)  # pasada la hora vuelve a poder
    with pytest.raises(limits.LimiteExcedido, match="por día"):
        limits.consumir("ana", t + 7300)
    limits.consumir("ana", t + 86_401)  # al dia siguiente


def test_el_endpoint_responde_429_al_pasar_el_limite(monkeypatch, cliente_chat):
    monkeypatch.setattr(config, "LLM_MAX_REQUESTS_PER_HOUR", 1)
    llm.reiniciar(ProveedorFalso())
    cliente = cliente_chat
    cuerpo = {"message": "hola", "agent_type": "inventory"}
    assert cliente.post("/api/chat", json=cuerpo).status_code == 200
    r = cliente.post("/api/chat", json=cuerpo)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0 and "por hora" in r.json()["detail"]


def test_sin_modelo_no_hay_limite(monkeypatch, cliente_chat):
    monkeypatch.setattr(config, "LLM_MAX_REQUESTS_PER_HOUR", 1)
    llm.reiniciar(None)
    cliente = cliente_chat
    for _ in range(3):
        assert cliente.post("/api/chat", json={"message": "hola", "agent_type": "inventory"}).status_code == 200

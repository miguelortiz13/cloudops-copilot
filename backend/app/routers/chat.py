
from fastapi import APIRouter, HTTPException
from app.schemas.inventory import *
from app.schemas.requests import *
from app.core.authz import Usuario, requiere
from app import llm
from app.ai import asistente
from app.core.deps import AgentDep, AzureDep
from app.llm.limits import exigir_cupo


router = APIRouter(tags=['chat'])

@router.post("/api/chat", response_model=ChatResponse)
def post_chat(agent: AgentDep, azure: AzureDep, req: ChatRequest, usuario: Usuario = requiere("lector")):
    exigir_cupo(usuario.actor)
    # Con un modelo que admite herramientas responde el motor de agentes (app/ai); si falla, el
    # agente de siempre (contexto precargado o motor de reglas).
    if llm.con_herramientas():
        try:
            r = asistente.responder(req.message, req.agent_type, azure.azure_credentials, usuario=usuario.actor)
            return ChatResponse(answer=r["answer"], mode=f"llm_{llm.proveedor().nombre}_herramientas", data=r["tools"])
        except llm.LLMError as exc:
            print(f"[chat] El motor de agentes falló, se usa el agente anterior: {exc}")
    try:
        response = agent.ask(req.message, agent_type=req.agent_type or "inventory", subscriptions=req.subscriptions,
                             usuario=usuario.actor)
        return ChatResponse(
            answer=response["answer"],
            mode=response["mode"],
            data=response["data"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




from fastapi import APIRouter, HTTPException
from app.schemas.inventory import *
from app.schemas.k8s import *
from app.schemas.requests import *
from app.core.authz import Usuario, requiere
from app.core.deps import AgentDep
from app.llm.limits import exigir_cupo


router = APIRouter(tags=['chat'])

@router.post("/api/chat", response_model=ChatResponse)
def post_chat(agent: AgentDep, req: ChatRequest, usuario: Usuario = requiere("lector")):
    exigir_cupo(usuario.actor)
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



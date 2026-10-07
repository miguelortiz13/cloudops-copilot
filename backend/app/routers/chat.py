
from fastapi import APIRouter, HTTPException
from app.schemas.inventory import *
from app.schemas.k8s import *
from app.schemas.requests import *
from app.core.deps import AgentDep


router = APIRouter(tags=['chat'])

@router.post("/api/chat", response_model=ChatResponse)
def post_chat(agent: AgentDep, req: ChatRequest):
    try:
        response = agent.ask(req.message, agent_type=req.agent_type or "inventory", subscriptions=req.subscriptions)
        return ChatResponse(
            answer=response["answer"],
            mode=response["mode"],
            data=response["data"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



from pydantic import BaseModel
from typing import Dict, Any, List, Optional
class ChatRequest(BaseModel):
    message: str
    agent_type: Optional[str] = "inventory"
    subscriptions: Optional[List[str]] = None
    context: Dict[str, Any] = {}
class WebhookTestRequest(BaseModel):
    webhook_url: str
    alert_type: str
class RecommendationActionRequest(BaseModel):
    action: str
class IaCGenerateRequest(BaseModel):
    """
    Peticion de generacion de Terraform para un recurso.

    El esquema declaraba `resources: List[Dict]`, una forma que ni el frontend
    enviaba ni el endpoint leia —usa `req.resource_id`—, asi que FastAPI
    rechazaba cada llamada con un 422 antes de ejecutar nada. El modulo de IaC
    llevaba roto desde que main.py se repartio en routers.
    """
    resource_id: str
    environment: str = "dev"
    domain: str = "platform"
class ChatResponse(BaseModel):
    answer: str
    mode: str
    data: List[Dict[str, Any]]

"""
Incidentes: ingesta de alertas y su diagnóstico por el agente (app/ai/incidentes.py).

`POST /api/alerts/alertmanager` no lleva token de Entra ID (la llama
Alertmanager): se autentica con `ALERTS_INGEST_TOKEN` como bearer. Responde
enseguida y el diagnóstico corre en segundo plano.
"""

import hmac
import os
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.ai import incidentes
from app.core.audit import auditar
from app.core.authz import Usuario, requiere
from app.core.deps import AzureDep
from app.db import engine as db
from app.db.models import Incident

router = APIRouter(tags=["incidentes"])
MAX_BYTES = 1_000_000


def _iso(m):
    return m.isoformat() if m else None


@router.post("/api/alerts/alertmanager", status_code=202)
async def alertmanager(request: Request, tareas: BackgroundTasks, azure: AzureDep, cluster: Optional[str] = None,
                       authorization: str = Header(default="")):
    """Webhook de Alertmanager (`webhook_configs`). `cluster`: el clúster de las alertas (como lo conoce la plataforma)."""
    esperado = os.getenv("ALERTS_INGEST_TOKEN", "")
    if not esperado:
        raise HTTPException(status_code=503, detail="La ingesta de alertas no está configurada (ALERTS_INGEST_TOKEN).")
    if not hmac.compare_digest(authorization.encode(), f"Bearer {esperado}".encode()):
        raise HTTPException(status_code=401, detail="Token de ingesta inválido.")
    cuerpo = await request.body()
    if len(cuerpo) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Alerta demasiado grande.")
    if cluster is not None and (len(cluster) > 60 or not cluster.replace("-", "").isalnum()):
        raise HTTPException(status_code=400, detail="Nombre de clúster inválido.")
    if not db.is_configured():
        raise HTTPException(status_code=503, detail="Sin base de datos: Alertmanager reintentará.")
    try:
        incidente, accion = incidentes.ingresar_alertmanager(await request.json(), cluster)
    except (incidentes.AlertaInvalida, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except db.DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Base no disponible: {exc}")
    # shortcut: el diagnóstico corre en el proceso del API tras responder; si la réplica escala a cero a mitad
    # (enfría a los 5 min, el diagnóstico tarda < 2), se pierde. Pasar a una cola y un job si eso ocurre.
    if accion == "nuevo":
        tareas.add_task(incidentes.diagnosticar, incidente, azure.azure_credentials)
    elif accion == "resuelto":
        tareas.add_task(incidentes.reportar, incidente)
    return {"incident": incidente, "action": accion}


def _resumen(i: Incident) -> dict:
    return {"id": i.id, "title": i.title, "severity": i.severity, "status": i.status, "cluster": i.cluster,
            "source": i.source, "opened_at": _iso(i.opened_at), "resolved_at": _iso(i.resolved_at),
            "diagnosis_status": i.diagnosis_status, "feedback": i.feedback, "alerts": len(i.alerts)}


@router.get("/api/incidents")
def listar():
    if not db.is_configured():
        return {"configured": False, "items": []}
    try:
        with db.session_scope() as s:
            return {"configured": True, "items": [_resumen(i) for i in s.scalars(
                select(Incident).order_by(Incident.opened_at.desc()).limit(100))]}
    except db.DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Base no disponible: {exc}")


@router.get("/api/incidents/{incidente_id}")
def detalle(incidente_id: int):
    try:
        with db.session_scope() as s:
            i = s.get(Incident, incidente_id)
            if i is None:
                raise HTTPException(status_code=404, detail="No existe ese incidente.")
            return {**_resumen(i), "alert_list": i.alerts, "diagnosis": i.diagnosis, "tools": i.diagnosis_tools,
                    "diagnosed_at": _iso(i.diagnosed_at), "last_alert_at": _iso(i.last_alert_at)}
    except db.DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Base no disponible: {exc}")


class Opinion(BaseModel):
    value: Literal["correcto", "incorrecto"]


@router.post("/api/incidents/{incidente_id}/feedback")
def opinion(incidente_id: int, body: Opinion, usuario: Usuario = requiere("operador")):
    with db.session_scope() as s:
        i = s.get(Incident, incidente_id)
        if i is None:
            raise HTTPException(status_code=404, detail="No existe ese incidente.")
        i.feedback = body.value
    auditar(usuario, "incidente.diagnostico", objetivo=str(incidente_id), detalle={"feedback": body.value})
    return {"id": incidente_id, "feedback": body.value}

"""
Incidentes: ingesta de alertas y su diagnóstico por el agente (app/ai/incidentes.py).

`POST /api/alerts/alertmanager` no lleva token de Entra ID (la llama
Alertmanager): se autentica con `ALERTS_INGEST_TOKEN` como bearer. Responde
enseguida y el diagnóstico corre en segundo plano.

La gestión (estado, responsable, notas, volver a diagnosticar, post-mortem y
silencios) es del operador; los ajustes, del administrador. Todo queda auditado
y en la línea de tiempo del incidente.
"""

import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.ai import incidentes
from app.core import ajustes
from app.core.audit import auditar
from app.core.authz import Usuario, requiere
from app.core.deps import AzureDep
from app.db import engine as db
from app.db.models import Incident, IncidentEvent

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
    if accion in ("nuevo", "tormenta"):
        tareas.add_task(incidentes.diagnosticar, incidente, azure.azure_credentials)
    elif accion == "resuelto":
        tareas.add_task(incidentes.al_resolverse, incidente)
    return {"incident": incidente, "action": accion}


def _resumen(i: Incident) -> dict:
    return {"id": i.id, "title": i.title, "severity": i.severity, "status": i.status, "cluster": i.cluster,
            "source": i.source, "opened_at": _iso(i.opened_at), "resolved_at": _iso(i.resolved_at),
            "diagnosis_status": i.diagnosis_status, "feedback": i.feedback, "alerts": len(i.alerts),
            "assignee": i.assignee, "closed_reason": i.closed_reason, "parent_id": i.parent_id}


@router.get("/api/incidents")
def listar(estado: Optional[Literal["vivos", "abierto", "reconocido", "en_curso", "resuelto", "cerrado"]] = None,
           severidad: Optional[Literal["critica", "alta", "media"]] = None, cluster: Optional[str] = None,
           dias: int = Query(default=30, ge=1, le=365), agrupados: bool = False):
    """Últimos 200 incidentes con filtros. Sin `agrupados`, los que cuelgan de una tormenta no salen sueltos."""
    if not db.is_configured():
        return {"configured": False, "items": []}
    q = select(Incident).where(Incident.opened_at >= datetime.now(timezone.utc) - timedelta(days=dias))
    if estado:
        q = q.where(Incident.status.in_(incidentes.ABIERTOS) if estado == "vivos" else Incident.status == estado)
    if severidad:
        q = q.where(Incident.severity == severidad)
    if cluster:
        q = q.where(Incident.cluster == cluster)
    if not agrupados:
        q = q.where(Incident.parent_id.is_(None))
    try:
        with db.session_scope() as s:
            return {"configured": True, "items": [_resumen(i) for i in s.scalars(q.order_by(Incident.opened_at.desc()).limit(200))]}
    except db.DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Base no disponible: {exc}")


@router.get("/api/incidents/stats")
def metricas(dias: int = Query(default=30, ge=1, le=365)):
    """Precisión del diagnóstico según las marcas de las personas, y tiempos de resolución."""
    if not db.is_configured():
        return {"configured": False}
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    with db.session_scope() as s:
        filas = list(s.scalars(select(Incident).where(Incident.opened_at >= desde, Incident.parent_id.is_(None))))
    marcados = [i for i in filas if i.feedback]
    correctos = sum(1 for i in marcados if i.feedback == "correcto")
    minutos = sorted(int((i.resolved_at - i.opened_at).total_seconds() // 60) for i in filas if i.resolved_at)
    return {"configured": True, "days": dias, "total": len(filas),
            "open": sum(1 for i in filas if i.status in incidentes.ABIERTOS),
            "diagnosed": sum(1 for i in filas if i.diagnosis_status == "listo"),
            "marked": len(marcados), "correct": correctos,
            "accuracy": round(correctos / len(marcados), 3) if marcados else None, "target": 0.9,
            "noise": sum(1 for i in filas if i.closed_reason in ("falso_positivo", "ruido")),
            "median_minutes_to_resolve": minutos[len(minutos) // 2] if minutos else None}


@router.get("/api/incidents/{incidente_id}")
def detalle(incidente_id: int):
    try:
        with db.session_scope() as s:
            i = s.get(Incident, incidente_id)
            if i is None:
                raise HTTPException(status_code=404, detail="No existe ese incidente.")
            hijos = [_resumen(h) for h in s.scalars(select(Incident).where(Incident.parent_id == i.id).order_by(Incident.id))]
            eventos = [{"at": _iso(e.at), "actor": e.actor, "kind": e.kind, "text": e.text} for e in s.scalars(
                select(IncidentEvent).where(IncidentEvent.incident_id == i.id).order_by(IncidentEvent.id))]
            return {**_resumen(i), "alert_list": i.alerts, "diagnosis": i.diagnosis, "tools": i.diagnosis_tools,
                    "diagnosed_at": _iso(i.diagnosed_at), "last_alert_at": _iso(i.last_alert_at),
                    "postmortem": i.postmortem, "children": hijos, "events": eventos}
    except db.DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Base no disponible: {exc}")


def _cambiar(incidente_id: int, usuario: Usuario, accion: str, tipo: str, texto: str, cambio) -> Dict[str, Any]:
    """Aplica `cambio(incidente)` (que puede lanzar HTTPException), lo deja en la línea de tiempo y lo audita."""
    with db.session_scope() as s:
        i = s.get(Incident, incidente_id)
        if i is None:
            raise HTTPException(status_code=404, detail="No existe ese incidente.")
        cambio(i)
        incidentes.evento(s, i.id, usuario.actor, tipo, texto)
        salida = _resumen(i)
    auditar(usuario, accion, objetivo=str(incidente_id), detalle={"texto": texto[:200]})
    return salida


class Estado(BaseModel):
    status: Literal["abierto", "reconocido", "en_curso", "cerrado"]
    reason: Optional[Literal["solucionado", "falso_positivo", "ruido", "duplicado"]] = None
    comment: str = Field(default="", max_length=1000)


ETIQUETAS = {"abierto": "Reabierto", "reconocido": "Reconocido", "en_curso": "En curso", "cerrado": "Cerrado"}


@router.post("/api/incidents/{incidente_id}/status")
def estado(incidente_id: int, body: Estado, tareas: BackgroundTasks, usuario: Usuario = requiere("operador")):
    """Ciclo de vida a mano. Cerrar pide motivo; cerrar como solucionado redacta el post-mortem si está activado."""
    if body.status == "cerrado" and not body.reason:
        raise HTTPException(status_code=400, detail="Para cerrar hace falta el motivo.")

    def cambio(i: Incident):
        if body.status == "cerrado":
            if i.status in ("resuelto", "cerrado"):
                raise HTTPException(status_code=409, detail="El incidente ya terminó.")
            i.status, i.closed_reason, i.resolved_at = "cerrado", body.reason, datetime.now(timezone.utc)
        else:
            if i.status == "resuelto" and body.status != "abierto":
                raise HTTPException(status_code=409, detail="La fuente ya lo resolvió; solo se puede reabrir.")
            i.status = body.status
            if body.status == "abierto":
                i.closed_reason, i.resolved_at = None, None
        if body.status != "abierto" and not i.assignee:
            i.assignee = usuario.actor  # quien lo toma, salvo que ya tenga responsable

    texto = ETIQUETAS[body.status] + (f" ({body.reason.replace('_', ' ')})" if body.reason else "") + (f": {body.comment}" if body.comment else "")
    salida = _cambiar(incidente_id, usuario, "incidente.estado", "estado", texto, cambio)
    if body.status == "cerrado" and body.reason == "solucionado" and ajustes.incidentes()["postmortem"]:
        tareas.add_task(incidentes.redactar_postmortem, incidente_id, usuario.actor)
    return salida


class Responsable(BaseModel):
    assignee: Optional[str] = Field(default=None, max_length=200)


@router.post("/api/incidents/{incidente_id}/assign")
def asignar(incidente_id: int, body: Responsable, usuario: Usuario = requiere("operador")):
    """Responsable del incidente (texto libre: correo o nombre). Vacío lo deja sin responsable."""
    quien = (body.assignee or "").strip() or None

    def cambio(i: Incident):
        i.assignee = quien

    return _cambiar(incidente_id, usuario, "incidente.asignar", "asignado",
                    f"Responsable: {quien}" if quien else "Sin responsable", cambio)


class Nota(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.post("/api/incidents/{incidente_id}/notes")
def nota(incidente_id: int, body: Nota, usuario: Usuario = requiere("operador")):
    return _cambiar(incidente_id, usuario, "incidente.nota", "nota", body.text.strip(), lambda i: None)


@router.post("/api/incidents/{incidente_id}/rediagnose", status_code=202)
def rediagnosticar(incidente_id: int, tareas: BackgroundTasks, azure: AzureDep, usuario: Usuario = requiere("operador")):
    """Vuelve a diagnosticar (con la foto de ahora); cuenta contra el tope de diagnósticos."""
    def cambio(i: Incident):
        if i.diagnosis_status == "diagnosticando":
            raise HTTPException(status_code=409, detail="Ya se está diagnosticando.")
        i.diagnosis_status = "diagnosticando"

    salida = _cambiar(incidente_id, usuario, "incidente.rediagnosticar", "diagnostico", "Pidió volver a diagnosticar.", cambio)
    tareas.add_task(incidentes.diagnosticar, incidente_id, azure.azure_credentials, usuario.actor)
    return salida


@router.post("/api/incidents/{incidente_id}/postmortem")
def postmortem(incidente_id: int, usuario: Usuario = requiere("operador")):
    """Redacta (o rehace) el borrador de post-mortem ahora y lo devuelve."""
    with db.session_scope() as s:
        if s.get(Incident, incidente_id) is None:
            raise HTTPException(status_code=404, detail="No existe ese incidente.")
    texto = incidentes.redactar_postmortem(incidente_id, usuario.actor)
    if texto is None:
        raise HTTPException(status_code=503, detail="No se pudo redactar: sin modelo o tope de diagnósticos alcanzado.")
    auditar(usuario, "incidente.postmortem", objetivo=str(incidente_id))
    return {"id": incidente_id, "postmortem": texto}


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


# ---------------------------------------------------------------- silencios y ajustes

class Silencio(BaseModel):
    hours: float = Field(gt=0, le=720)
    reason: str = Field(default="", max_length=300)
    cluster: Optional[str] = Field(default=None, max_length=200)
    namespace: Optional[str] = Field(default=None, max_length=200)
    alertname: Optional[str] = Field(default=None, max_length=200)
    target: Optional[str] = Field(default=None, max_length=200)


@router.get("/api/silences")
def listar_silencios():
    return {"items": ajustes.silencios()}


@router.post("/api/silences", status_code=201)
def crear_silencio(body: Silencio, usuario: Usuario = requiere("operador")):
    """Silencia alertas e incidencias de Kubernetes que coinciden (campos vacíos: cualquiera). Ni se diagnostican ni se avisan."""
    try:
        s = ajustes.silenciar(usuario.actor, body.hours, body.reason, cluster=body.cluster or None,
                              namespace=body.namespace or None, alerta=body.alertname or None, objeto=body.target or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    auditar(usuario, "silencio.crear", objetivo=s["id"], detalle={k: s[k] for k in ("cluster", "namespace", "alerta", "objeto", "hasta")})
    return s


@router.delete("/api/silences/{silencio_id}")
def quitar_silencio(silencio_id: str, usuario: Usuario = requiere("operador")):
    if not ajustes.quitar_silencio(silencio_id):
        raise HTTPException(status_code=404, detail="No existe ese silencio.")
    auditar(usuario, "silencio.quitar", objetivo=silencio_id)
    return {"id": silencio_id, "removed": True}


@router.get("/api/settings/incidents")
def ver_ajustes():
    return {"values": ajustes.incidentes(), "defaults": ajustes.INCIDENTES, "limits": ajustes.LIMITES}


@router.put("/api/settings/incidents")
def cambiar_ajustes(body: Dict[str, Any], usuario: Usuario = requiere("administrador")):
    try:
        valores = ajustes.guardar_incidentes(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    auditar(usuario, "ajustes.incidentes", detalle=body)
    return {"values": valores}

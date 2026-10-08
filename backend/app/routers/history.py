"""
Vistas que leen de la base: historia de costos, KPIs y gestion de hallazgos.

Responden desde la cache que deja el recolector (ver app/readmodel). Sin base,
o con la base pausada por haber agotado el cupo gratuito del mes, responden 503
y el panel vuelve a las vistas en vivo.
"""

from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.audit import auditar
from app.core.authz import Usuario, requiere
from app.db import engine as db
from app.readmodel import queries, service

router = APIRouter(tags=["history"])


def _no_disponible(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=f"Historia no disponible: {exc}")


def _guardia():
    if not db.is_configured():
        raise HTTPException(status_code=503, detail="Historia no disponible: la base de datos no está configurada.")


@router.get("/api/history/costs")
def history_costs(period: str = "30d"):
    _guardia()
    try:
        return service.costos(period)
    except queries.PeriodoInvalido as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except db.DatabaseUnavailable as exc:
        raise _no_disponible(exc)


@router.get("/api/history/kpis")
def history_kpis(days: int = queries.DIAS_KPI_POR_DEFECTO):
    _guardia()
    if not 7 <= days <= 400:
        raise HTTPException(status_code=400, detail="days debe estar entre 7 y 400.")
    try:
        return service.kpis(days)
    except db.DatabaseUnavailable as exc:
        raise _no_disponible(exc)


@router.get("/api/findings")
def list_findings():
    _guardia()
    try:
        return service.hallazgos()
    except db.DatabaseUnavailable as exc:
        raise _no_disponible(exc)


@router.get("/api/findings/{finding_id}/events")
def finding_events(finding_id: int):
    _guardia()
    try:
        return service.eventos(finding_id)
    except db.DatabaseUnavailable as exc:
        raise _no_disponible(exc)


class CambioDeEstado(BaseModel):
    status: Literal["abierto", "asumido", "aceptado"]
    note: Optional[str] = Field(default=None, max_length=2000)
    accepted_until: Optional[date] = None
    owner: Optional[str] = Field(default=None, max_length=320)


@router.post("/api/findings/{finding_id}/status")
def change_finding_status(finding_id: int, body: CambioDeEstado, usuario: Usuario = requiere("operador")):
    _guardia()
    try:
        resultado = service.cambiar_estado(finding_id, body.status, usuario.actor, body.note, body.accepted_until, body.owner)
        auditar(usuario, "hallazgo.estado", objetivo=resultado["resource_uid"], detalle={
            "finding_id": finding_id, "rule": resultado["rule_id"], "status": body.status,
            "accepted_until": body.accepted_until, "note": body.note})
        return resultado
    except service.CambioInvalido as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except db.DatabaseUnavailable as exc:
        raise _no_disponible(exc)

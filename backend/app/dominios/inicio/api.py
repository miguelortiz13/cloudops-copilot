"""Rutas del dominio Inicio (`/api/inicio/...`, fase 5 del plan 10)."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.authz import Usuario, requiere
from app.db import engine as db
from app.dominios.inicio import servicio

router = APIRouter(tags=["inicio"])


@router.get("/api/inicio/pendientes")
def pendientes(usuario: Usuario = requiere("lector")):
    """Lo que espera a quien consulta, por urgencia y con el porqué."""
    if not db.is_configured():
        return {"configured": False, "items": []}
    return {"configured": True, "actor": usuario.actor, "items": servicio.pendientes(usuario.actor)}


@router.get("/api/inicio/cambios")
def cambios(desde: Optional[datetime] = Query(default=None, description="Última visita; por defecto, hace 24 horas"),
            usuario: Usuario = requiere("lector")):
    if not db.is_configured():
        return {"configured": False}
    ahora = datetime.now(timezone.utc)
    desde = desde or ahora - timedelta(hours=24)
    if desde.tzinfo is None:
        desde = desde.replace(tzinfo=timezone.utc)
    if desde < ahora - timedelta(days=30):
        desde = ahora - timedelta(days=30)  # una visita muy vieja no recorre todo el historial
    if desde > ahora:
        raise HTTPException(status_code=400, detail="`desde` no puede estar en el futuro.")
    return {"configured": True, **servicio.cambios(desde)}

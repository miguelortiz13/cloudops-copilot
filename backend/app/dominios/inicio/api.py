"""Rutas del dominio Inicio (`/api/inicio/...`, fase 5 del plan 10)."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app import llm
from app.core.authz import Usuario, requiere
from app.db import engine as db
from app.dominios.inicio import servicio
from app.llm.limits import exigir_cupo

router = APIRouter(tags=["inicio"])


@router.get("/api/inicio/pendientes")
def pendientes(usuario: Usuario = requiere("lector")):
    """Lo que espera a quien consulta, por urgencia y con el porqué."""
    if not db.is_configured():
        return {"configured": False, "items": []}
    return {"configured": True, "actor": usuario.actor, "items": servicio.pendientes(usuario.actor)}


@router.post("/api/inicio/pendientes/priorizar")
def priorizar(usuario: Usuario = requiere("lector")):
    """La IA propone por dónde empezar con mis pendientes (agrupa los de la misma causa y dice la acción)."""
    if not db.is_configured():
        raise HTTPException(status_code=503, detail="Sin base de datos no hay pendientes.")
    if not llm.disponible():
        raise HTTPException(status_code=503, detail="No hay un modelo de lenguaje configurado.")
    items = servicio.pendientes(usuario.actor)
    if not items:
        return {"text": "No tienes pendientes: nada que priorizar.", "items": 0, "cached": False}
    try:
        return servicio.priorizar(usuario.actor, items, cobrar=lambda: exigir_cupo(usuario.actor))
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=f"El modelo no respondió: {str(exc)[:200]}")


@router.get("/api/inicio/valor")
def valor(semanas: int = Query(default=8, ge=2, le=26), usuario: Usuario = requiere("lector")):
    """Tablero de valor (fase 7.2): indicadores de operación por semana, ahorro realizado y evals."""
    from app.dominios.inicio import valor as tablero

    if not db.is_configured():
        return {"configured": False}
    return {"configured": True, **tablero.tablero(semanas)}


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

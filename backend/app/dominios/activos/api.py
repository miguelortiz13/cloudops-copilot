"""Rutas del dominio Activos (`/api/activos/...`, fase 3 del plan 10)."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app import llm
from app.core.authz import Usuario, requiere
from app.db import engine as db
from app.dominios.activos import servicio
from app.llm.limits import exigir_cupo

router = APIRouter(tags=["activos"])


@router.get("/api/activos/recursos")
def recursos(q: str = Query(default="", max_length=200), nube: str = "", cuenta: str = "", tipo: str = "",
             en_terraform: Optional[bool] = None, pagina: int = Query(default=1, ge=1),
             por_pagina: int = Query(default=50, ge=1, le=200)):
    """Recursos de todas las nubes (desde la caché del inventario), ordenados por gasto."""
    return servicio.recursos(q, nube, cuenta, tipo, en_terraform, pagina, por_pagina)


@router.get("/api/activos/ficha")
def ficha(uid: str = Query(max_length=600)):
    """Ficha única: inventario, gasto, hallazgos, clasificación, incidentes y línea de tiempo del recurso."""
    if not db.is_configured():
        raise HTTPException(status_code=503, detail="Sin base de datos: la ficha sale de lo que guarda el recolector.")
    try:
        return servicio.ficha(uid)
    except servicio.NoExiste:
        raise HTTPException(status_code=404, detail="Ese recurso no está en el inventario.")
    except db.DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Base no disponible: {exc}")


class Pedido(BaseModel):
    uid: str = Field(max_length=600)


@router.post("/api/activos/ficha/explicacion")
def explicacion(body: Pedido, usuario: Usuario = requiere("lector")):
    """La IA explica el recurso: qué es, cuánto cuesta, sus riesgos y qué haría. Cuenta contra el cupo del usuario."""
    if not llm.disponible():
        raise HTTPException(status_code=503, detail="No hay un modelo de lenguaje configurado.")
    exigir_cupo(usuario.actor)
    try:
        return {"uid": body.uid, "explanation": servicio.explicar(body.uid, usuario.actor)}
    except servicio.NoExiste:
        raise HTTPException(status_code=404, detail="Ese recurso no está en el inventario.")
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=f"El modelo no respondió: {str(exc)[:200]}")

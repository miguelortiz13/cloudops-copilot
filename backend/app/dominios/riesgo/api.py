"""Rutas del dominio Riesgo (`/api/riesgo/...`, fase 3 del plan 10)."""

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import llm
from app.core.audit import auditar
from app.core.authz import Usuario, requiere
from app.db import engine as db
from app.dominios.riesgo import servicio
from app.llm.limits import exigir_cupo

router = APIRouter(tags=["riesgo"])


def _base():
    if not db.is_configured():
        raise HTTPException(status_code=503, detail="Sin base de datos: las excepciones se guardan allí.")


@router.get("/api/riesgo/excepciones")
def excepciones():
    _base()
    return {"items": servicio.listar()}


class Excepcion(BaseModel):
    framework: str = Field(max_length=64)
    control: str = Field(max_length=64)
    justification: str = Field(max_length=2000)
    until: date


@router.post("/api/riesgo/excepciones", status_code=201)
def crear(body: Excepcion, usuario: Usuario = requiere("operador")):
    """Exceptúa un control hasta `until` (máx. 1 año) con su justificación. Una vigente por control."""
    _base()
    try:
        e = servicio.crear(body.framework, body.control, body.justification, body.until, usuario.actor)
    except servicio.ExcepcionInvalida as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    auditar(usuario, "control.excepcion", objetivo=f"{body.framework}:{body.control}",
            detalle={"hasta": body.until.isoformat(), "justificacion": body.justification[:300]})
    return e


@router.delete("/api/riesgo/excepciones/{excepcion_id}")
def revocar(excepcion_id: int, usuario: Usuario = requiere("operador")):
    _base()
    try:
        e = servicio.revocar(excepcion_id, usuario.actor)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    auditar(usuario, "control.excepcion_revocada", objetivo=f"{e['framework']}:{e['control']}")
    return e


class Pedido(BaseModel):
    framework: str = Field(max_length=64)
    control: str = Field(max_length=64)


@router.post("/api/riesgo/excepciones/borrador")
def borrador(body: Pedido, usuario: Usuario = requiere("operador")):
    """La IA redacta un borrador de justificación con la evidencia del control. Cuenta contra el cupo del usuario."""
    if not llm.disponible():
        raise HTTPException(status_code=503, detail="No hay un modelo de lenguaje configurado.")
    exigir_cupo(usuario.actor)
    try:
        return {"justification": servicio.borrador(body.framework, body.control, usuario.actor)}
    except servicio.ExcepcionInvalida as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=f"El modelo no respondió: {str(exc)[:200]}")

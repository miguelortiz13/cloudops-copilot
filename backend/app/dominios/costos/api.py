"""Rutas del dominio Costos (`/api/costos/...`, fase 4 del plan 10)."""

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app import llm
from app.core.audit import auditar
from app.core.authz import Usuario, requiere
from app.db import engine as db
from app.dominios.costos import servicio
from app.llm.limits import exigir_cupo

router = APIRouter(tags=["costos"])


def _base():
    if not db.is_configured():
        raise HTTPException(status_code=503, detail="Sin base de datos: las alertas de costo se guardan allí.")


@router.get("/api/costos/alertas")
def alertas(estado: Optional[Literal["vivos", "abierto", "reconocido", "resuelto", "descartado"]] = None,
            dias: int = Query(default=90, ge=1, le=365)):
    _base()
    return servicio.listar(estado, dias)


class Cambio(BaseModel):
    status: Optional[Literal["abierto", "reconocido", "resuelto", "descartado"]] = None
    assignee: Optional[str] = Field(default=None, max_length=200)
    note: Optional[str] = Field(default=None, max_length=2000)


@router.post("/api/costos/alertas/{evento_id}")
def cambiar(evento_id: int, body: Cambio, usuario: Usuario = requiere("operador")):
    """Estado (reconocido, resuelto, descartado o reabrir), responsable y nota de una alerta de costo."""
    _base()
    try:
        e = servicio.cambiar(evento_id, body.status, body.assignee, body.note, usuario.actor)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    auditar(usuario, "costo.alerta", objetivo=str(evento_id), detalle=body.model_dump(exclude_none=True))
    return e


@router.post("/api/costos/alertas/{evento_id}/explicacion")
def explicacion(evento_id: int, usuario: Usuario = requiere("lector")):
    """La IA explica la alerta: qué servicio o recurso explica la diferencia y si coincide con un recurso nuevo."""
    _base()
    if not llm.disponible():
        raise HTTPException(status_code=503, detail="No hay un modelo de lenguaje configurado.")
    exigir_cupo(usuario.actor)
    try:
        return {"id": evento_id, "explanation": servicio.explicar(evento_id, usuario.actor)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=f"El modelo no respondió: {str(exc)[:200]}")


class Aplicada(BaseModel):
    resource_id: str = Field(max_length=450)
    name: str = Field(max_length=260)
    category: str = Field(max_length=100)
    expected_monthly: float = Field(ge=0, le=1_000_000)
    note: Optional[str] = Field(default=None, max_length=2000)


@router.post("/api/costos/ahorro/aplicadas", status_code=201)
def aplicar(body: Aplicada, usuario: Usuario = requiere("operador")):
    """Marca una oportunidad de ahorro como aplicada; se verifica sola cuando el recurso desaparece del inventario."""
    from app.dominios.costos import ahorro

    _base()
    uid = body.resource_id if ":" in body.resource_id.split("/", 1)[0] else f"azure:{body.resource_id.lower()}"
    a = ahorro.aplicar(uid, body.name, body.category, body.expected_monthly, body.note, usuario.actor)
    auditar(usuario, "costo.ahorro_aplicado", objetivo=uid, detalle={"esperado": body.expected_monthly, "categoria": body.category})
    return a


@router.get("/api/costos/ahorro/realizado")
def ahorro_realizado(dias: int = Query(default=90, ge=1, le=365)):
    """Aplicadas (pendientes y verificadas con su ahorro real) y bajas del periodo con el gasto mensual evitado."""
    from app.dominios.costos import ahorro

    _base()
    return ahorro.realizado(dias)

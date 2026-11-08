"""Plataforma → IA (plan 11, hito IA-1): trazas del modelo y su resumen por dominio."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.core import ajustes, trazas
from app.core.authz import Usuario, requiere

router = APIRouter(tags=["plataforma"])


@router.get("/api/ia/resumen")
def resumen(dias: int = Query(default=7, ge=1, le=90), usuario: Usuario = requiere("operador")):
    """Llamadas, errores, tokens, costo estimado, latencia p50/p95 y herramientas, por dominio y por uso."""
    ia = ajustes.seccion("ia")
    return {"days": dias, **trazas.resumen(trazas.leer(dias), ia["precio_entrada_usd_1m"], ia["precio_salida_usd_1m"])}


@router.get("/api/ia/trazas")
def listar(dias: int = Query(default=1, ge=1, le=30), uso: Optional[str] = Query(default=None, max_length=64),
           limite: int = Query(default=100, ge=1, le=500), usuario: Usuario = requiere("operador")):
    """Las trazas más recientes (sin spans), filtrables por uso."""
    filas = [t for t in trazas.leer(dias) if not uso or t["attributes"]["cloudops.use"] == uso]
    return {"items": [{k: t[k] for k in ("trace_id", "name", "start", "duration_ms", "attributes")} | {"spans": len(t["spans"])}
                      for t in filas[:limite]], "total": len(filas)}


@router.get("/api/ia/trazas/{traza_id}")
def detalle(traza_id: str, usuario: Usuario = requiere("operador")):
    t = next((t for t in trazas.leer(30) if t["trace_id"] == traza_id), None)
    if t is None:
        raise HTTPException(status_code=404, detail="No existe esa traza en los últimos 30 días.")
    return t

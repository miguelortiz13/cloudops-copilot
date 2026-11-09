"""Plataforma → IA (plan 11, hito IA-1): trazas del modelo y su resumen por dominio."""

import hmac
import json
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request

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


# ---------------------------------------------------------------- evals (plan 11, hito IA-1)

def _carpeta_evals():
    from app.core import config
    return config.DATA_DIR / "evals"


@router.post("/api/ia/evals/ingesta", status_code=201)
async def publicar_evals(request: Request, authorization: str = Header(default="")):
    """
    La corrida semanal de evals (GitHub Actions) publica aquí su resultado, con el token de ingesta de la
    plataforma (el mismo de Alertmanager). Público con token propio, como /api/alerts/alertmanager.
    """
    esperado = os.getenv("ALERTS_INGEST_TOKEN", "")
    if not esperado:
        raise HTTPException(status_code=503, detail="La ingesta no está configurada (ALERTS_INGEST_TOKEN).")
    if not hmac.compare_digest(authorization.encode(), f"Bearer {esperado}".encode()):
        raise HTTPException(status_code=401, detail="Token de ingesta inválido.")
    cuerpo = await request.body()
    if len(cuerpo) > 200_000:
        raise HTTPException(status_code=413, detail="Resultado demasiado grande.")
    try:
        datos = json.loads(cuerpo)
        corrida = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": str(datos.get("model", ""))[:64],
                   "run": str(datos.get("run", ""))[:120],
                   "suites": [{k: s.get(k) for k in ("suite", "cases", "passed", "accuracy", "target", "invented_numbers", "details")}
                              for s in datos["suites"][:20]]}
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(status_code=400, detail="Se espera {model, run, suites: [...]}.")
    carpeta = _carpeta_evals()
    carpeta.mkdir(parents=True, exist_ok=True)
    with open(carpeta / "historial.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(corrida, ensure_ascii=False) + "\n")
    return {"stored": len(corrida["suites"])}


@router.get("/api/ia/evals")
def evals(limite: int = Query(default=12, ge=1, le=100), usuario: Usuario = requiere("operador")):
    """Las últimas corridas de evals, la más reciente primero."""
    try:
        with open(_carpeta_evals() / "historial.jsonl", encoding="utf-8") as f:
            corridas = [json.loads(linea) for linea in f if linea.strip()]
    except FileNotFoundError:
        corridas = []
    return {"runs": corridas[::-1][:limite]}


# ---------------------------------------------------------------- base de conocimiento (plan 11, hito IA-4)

@router.get("/api/ia/conocimiento")
def conocimiento_estado(usuario: Usuario = requiere("operador")):
    """Fragmentos indexados por tipo, cuántos con vector, modelo y última actualización."""
    from app.ai import conocimiento

    return conocimiento.estado()


@router.post("/api/ia/conocimiento/reindexar", status_code=202)
def conocimiento_reindexar(tareas: BackgroundTasks, usuario: Usuario = requiere("operador")):
    """Reindexa en segundo plano (el job diario lo hace solo); solo genera vectores para lo que cambió."""
    from app.ai import conocimiento
    from app.core.audit import auditar

    tareas.add_task(conocimiento.reindexar)
    auditar(usuario, "ia.conocimiento.reindexar")
    return {"started": True}


@router.get("/api/ia/conocimiento/buscar")
def conocimiento_buscar(q: str = Query(min_length=2, max_length=300), tipo: Optional[str] = Query(default=None, max_length=20),
                        usuario: Usuario = requiere("operador")):
    """La misma búsqueda que usa el agente, para probarla desde el panel."""
    from app.ai import conocimiento

    return conocimiento.buscar(q, tipo, 5)

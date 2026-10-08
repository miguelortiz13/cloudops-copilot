"""
Punto de entrada de las lecturas: cache primero, base despues.

Tambien concentra las escrituras del panel (gestion de hallazgos), que
invalidan la cache afectada.
"""

from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.db import engine as db
from app.db.models import Finding, FindingEvent
from app.readmodel import cache, queries

# Transiciones que una persona puede hacer. "resuelto" no esta: lo decide el
# recolector cuando el problema deja de detectarse.
TRANSICIONES = {
    "abierto": {"asumido", "aceptado"},
    "asumido": {"abierto", "aceptado"},
    "aceptado": {"abierto", "asumido"},
    "resuelto": set(),
}


class CambioInvalido(ValueError):
    pass


def _leer(nombre: str, params: Dict[str, Any], calcular: Callable[[Session], Any]) -> Any:
    llave = cache.clave(nombre, **params)
    guardado = cache.leer(llave)
    if guardado is not None:
        return {**guardado, "source": "cache"} if isinstance(guardado, dict) else guardado
    with db.session_scope() as s:
        datos = calcular(s)
    cache.guardar(llave, datos)
    return {**datos, "source": "database"} if isinstance(datos, dict) else datos


def costos(periodo: str) -> Dict[str, Any]:
    if periodo not in queries.PERIODOS:
        raise queries.PeriodoInvalido(f"Periodo desconocido: {periodo}")
    return _leer("costs", {"period": periodo}, lambda s: queries.costos(s, periodo))


def hallazgos() -> Dict[str, Any]:
    return _leer("findings", {}, queries.hallazgos)


def kpis(dias: int) -> Dict[str, Any]:
    return _leer("kpis", {"days": dias}, lambda s: queries.kpis(s, dias))


def eventos(hallazgo_id: int):
    # Se abre poco (al desplegar un hallazgo) y cambia con cada gestion: sin cache.
    with db.session_scope() as s:
        return queries.eventos(s, hallazgo_id)


def cambiar_estado(hallazgo_id: int, estado: str, actor: str, nota: Optional[str],
                   aceptado_hasta: Optional[date], responsable: Optional[str],
                   hoy: Optional[date] = None) -> Dict[str, Any]:
    hoy = hoy or datetime.now(timezone.utc).date()
    nota = (nota or "").strip() or None
    if estado == "aceptado":
        if not aceptado_hasta or aceptado_hasta <= hoy:
            raise CambioInvalido("Aceptar un riesgo exige una fecha de vencimiento futura.")
        if not nota:
            raise CambioInvalido("Aceptar un riesgo exige una justificación.")
    with db.session_scope() as s:
        f = s.get(Finding, hallazgo_id)
        if f is None:
            raise LookupError(f"No existe el hallazgo {hallazgo_id}.")
        if estado not in TRANSICIONES.get(f.status, set()):
            raise CambioInvalido(f"No se puede pasar de '{f.status}' a '{estado}'.")
        anterior = f.status
        f.status = estado
        f.accepted_until = aceptado_hasta if estado == "aceptado" else None
        if responsable is not None:
            f.owner = responsable.strip() or None
        if estado == "asumido" and not f.owner:
            f.owner = actor
        s.add(FindingEvent(finding_id=f.id, at=datetime.now(timezone.utc), kind="estado",
                           from_status=anterior, to_status=estado, actor=actor, note=nota))
        s.flush()
        cache.invalidar("findings")
        # La base esta despierta: se recalcula la vista ahora y no en la
        # siguiente visita.
        datos = queries.hallazgos(s)
    cache.guardar(cache.clave("findings"), datos)
    return next(h for h in datos["items"] if h["id"] == hallazgo_id)


def precalentar(s: Session) -> int:
    """Lo llama el recolector al terminar: deja calculadas las vistas por defecto."""
    escritas = 0
    for periodo in queries.PERIODOS_POR_DEFECTO:
        cache.guardar(cache.clave("costs", period=periodo), queries.costos(s, periodo))
        escritas += 1
    cache.guardar(cache.clave("findings"), queries.hallazgos(s))
    cache.guardar(cache.clave("kpis", days=queries.DIAS_KPI_POR_DEFECTO), queries.kpis(s, queries.DIAS_KPI_POR_DEFECTO))
    return escritas + 2

"""
Punto de entrada de las lecturas: cache primero, base despues.

Tambien concentra las escrituras del panel (gestion de hallazgos y
clasificacion de activos), que recalculan la cache afectada.
"""

from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.db import engine as db
from app.compliance.classification import CLASES, clasificar, custodio
from app.db.models import AssetClassification, Finding, FindingEvent, Resource
from app.readmodel import cache, cumplimiento as vistas_cumplimiento, queries

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


def cumplimiento() -> Dict[str, Any]:
    return _leer("compliance", {}, vistas_cumplimiento.cumplimiento)


def activos() -> Dict[str, Any]:
    return _leer("assets", {}, vistas_cumplimiento.activos)


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
        # La base esta despierta: se recalculan las vistas afectadas ahora y
        # no en la siguiente visita. El estado de los controles depende de los
        # hallazgos aceptados o asumidos.
        datos = queries.hallazgos(s)
        estado_de_controles = vistas_cumplimiento.cumplimiento(s)
    # Despues del commit: la cache nunca muestra un cambio que no quedo guardado.
    cache.guardar(cache.clave("findings"), datos)
    cache.guardar(cache.clave("compliance"), estado_de_controles)
    return next(h for h in datos["items"] if h["id"] == hallazgo_id)


def _vistas_de_clasificacion(s: Session) -> Callable[[str], Dict[str, Any]]:
    """Calcula las vistas con la base despierta; las guarda al llamar al resultado (tras el commit)."""
    datos, estado_de_controles = vistas_cumplimiento.activos(s), vistas_cumplimiento.cumplimiento(s)

    def publicar(uid: str) -> Dict[str, Any]:
        cache.guardar(cache.clave("assets"), datos)
        cache.guardar(cache.clave("compliance"), estado_de_controles)
        return next(a for a in datos["items"] if a["uid"] == uid)

    return publicar


def clasificar_a_mano(uid: str, clase: str, confidencialidad: int, integridad: int, disponibilidad: int,
                      analisis_de_riesgo: bool, motivo: Optional[str], responsable: Optional[str],
                      actor: str) -> Dict[str, Any]:
    """Fija una clasificacion que el recolector respetara."""
    motivo = (motivo or "").strip()
    if clase not in CLASES:
        raise CambioInvalido(f"Clasificación desconocida: {clase}.")
    if not motivo:
        raise CambioInvalido("Cambiar la clasificación exige un motivo.")
    with db.session_scope() as s:
        recurso = s.get(Resource, uid)
        if recurso is None or recurso.deleted_at is not None:
            raise LookupError("El recurso no existe en el inventario.")
        fila = s.get(AssetClassification, uid)
        if fila is None:
            fila = AssetClassification(resource_uid=uid)
            s.add(fila)
        fila.classification, fila.risk_required = clase, analisis_de_riesgo
        fila.confidentiality, fila.integrity, fila.availability = confidencialidad, integridad, disponibilidad
        fila.custodian = (responsable or "").strip() or fila.custodian or custodio(recurso.tags, recurso.created_by)
        fila.method, fila.reason = "manual", motivo
        fila.updated_by, fila.updated_at = actor, datetime.now(timezone.utc)
        s.flush()
        publicar = _vistas_de_clasificacion(s)
    return publicar(uid)


def restaurar_automatica(uid: str, actor: str) -> Dict[str, Any]:
    """Devuelve el recurso a la regla automatica, recalculada en el acto."""
    with db.session_scope() as s:
        recurso = s.get(Resource, uid)
        if recurso is None or recurso.deleted_at is not None:
            raise LookupError("El recurso no existe en el inventario.")
        c = clasificar(recurso.native_type, recurso.tags)
        fila = s.get(AssetClassification, uid) or AssetClassification(resource_uid=uid)
        s.add(fila)
        fila.classification, fila.risk_required, fila.reason = c.classification, c.risk_required, c.reason
        fila.confidentiality, fila.integrity, fila.availability = c.confidentiality, c.integrity, c.availability
        fila.custodian = custodio(recurso.tags, recurso.created_by)
        fila.method, fila.updated_by, fila.updated_at = "automatica", actor, datetime.now(timezone.utc)
        s.flush()
        publicar = _vistas_de_clasificacion(s)
    return publicar(uid)


def precalentar(s: Session) -> int:
    """Lo llama el recolector al terminar: deja calculadas las vistas por defecto."""
    escritas = 0
    for periodo in queries.PERIODOS_POR_DEFECTO:
        cache.guardar(cache.clave("costs", period=periodo), queries.costos(s, periodo))
        escritas += 1
    cache.guardar(cache.clave("findings"), queries.hallazgos(s))
    cache.guardar(cache.clave("kpis", days=queries.DIAS_KPI_POR_DEFECTO), queries.kpis(s, queries.DIAS_KPI_POR_DEFECTO))
    cache.guardar(cache.clave("compliance"), vistas_cumplimiento.cumplimiento(s))
    cache.guardar(cache.clave("assets"), vistas_cumplimiento.activos(s))
    return escritas + 4

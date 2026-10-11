"""
Recolector de inventario: cuentas y recursos.

Recibe el modelo canonico del proveedor (app/providers): no sabe de que nube
vienen. Un recurso que deja de aparecer se marca con `deleted_at`; si vuelve,
se limpia. Solo se marcan bajas cuando la consulta respondio: un inventario
incompleto (ProveedorError) aborta el recolector sin tocar nada.
"""

from typing import Dict, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.common import Contexto, Resultado
from app.db.models import Account, Resource
from app.providers.base import CapacidadNoSoportada, ProveedorError, resumen_capacidades


def recolectar(ctx: Contexto, session: Session) -> Resultado:
    momento = ctx.momento
    cuentas = {c.uid: c for c in ctx.cuentas}

    existentes_cuentas = {a.uid: a for a in session.scalars(select(Account).where(Account.uid.in_(cuentas)))}
    for uid, c in cuentas.items():
        cuenta = existentes_cuentas.get(uid)
        if cuenta is None:
            session.add(Account(uid=uid, provider=c.provider, native_id=c.native_id, name=c.name, parent=c.parent,
                                first_seen=momento, last_seen=momento))
        else:
            cuenta.name, cuenta.parent, cuenta.last_seen = c.name, c.parent, momento
    session.flush()

    # Si no respondio entero, ProveedorError aborta aqui, antes de marcar bajas.
    recursos = ctx.proveedor.recursos(list(cuentas))
    indice_iac, motivo_iac = _indice_iac(ctx)
    creadores, motivo_actividad = _creadores(ctx)

    existentes: Dict[str, Resource] = {
        r.uid: r for r in session.scalars(select(Resource).where(Resource.account_uid.in_(cuentas)))
    }
    vistos = set()
    nuevos = 0
    for item in recursos:
        if item.uid in vistos:
            continue
        vistos.add(item.uid)
        campos = dict(
            name=item.name,
            native_type=item.native_type,
            canonical_type=item.canonical_type,
            region=item.region,
            group_name=item.group_name,
            tags=dict(item.tags),
            in_iac_state=(item.uid in indice_iac) if indice_iac is not None else None,
            last_seen=momento,
            deleted_at=None,
        )
        recurso = existentes.get(item.uid)
        if recurso is None:
            nuevos += 1
            session.add(Resource(uid=item.uid, provider=item.provider, account_uid=item.account_uid,
                                 first_seen=momento, created_by=creadores.get(item.uid), **campos))
        else:
            for clave, valor in campos.items():
                setattr(recurso, clave, valor)
            # El historial de actividad es corto (~14 dias en Azure): no se
            # borra un creador conocido porque ya no aparezca.
            if creadores.get(item.uid):
                recurso.created_by = creadores[item.uid]

    bajas = 0
    for uid, recurso in existentes.items():
        if uid not in vistos and recurso.deleted_at is None:
            recurso.deleted_at = momento
            bajas += 1

    # Proveedor, capacidades y por que falta una: lo muestra Administracion
    # (cuentas conectadas) sin consultar la nube.
    return Resultado(items=len(vistos), detail={
        "accounts": len(cuentas), "new": nuevos, "deleted": bajas, "seen_at": momento.isoformat(),
        "iac_index": indice_iac is not None, "known_creators": len(creadores),
        "provider": ctx.proveedor.nombre, "capabilities": resumen_capacidades(ctx.proveedor),
        "unavailable": {k: v for k, v in (("iac", motivo_iac), ("actividad", motivo_actividad)) if v},
    })


def _indice_iac(ctx: Contexto) -> Tuple[Optional[Set[str]], Optional[str]]:
    """uids gestionados por Terraform, o None (no se sabe) con el motivo."""
    try:
        return set(ctx.proveedor.recursos_gestionados()), None
    except (CapacidadNoSoportada, ProveedorError) as exc:
        print(f"[recolector] Indice de Terraform no disponible: {exc}")
        return None, str(exc)


def _creadores(ctx: Contexto) -> Tuple[Dict[str, str], Optional[str]]:
    """Quien creo cada recurso creado a mano (en la ventana que conserve la nube), o el motivo de no saberlo."""
    try:
        actividad = ctx.proveedor.creaciones(ctx.cuentas_uid)
    except (CapacidadNoSoportada, ProveedorError) as exc:
        print(f"[recolector] Historial de creaciones no disponible: {exc}")
        return {}, str(exc)
    return {c.resource_uid: c.actor for c in actividad.creaciones if c.por_persona}, None

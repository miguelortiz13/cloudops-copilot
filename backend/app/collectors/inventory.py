"""
Recolector de inventario: cuentas y recursos.

Reutiliza la normalizacion de InventoryService (la misma que ve el panel) y la
lleva al modelo canonico. Un recurso que deja de aparecer se marca con
`deleted_at`; si vuelve, se limpia. Solo se marcan bajas cuando la consulta
respondio: una consulta fallida aborta el recolector sin tocar nada.
"""

from typing import Dict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.common import Contexto, Resultado, account_uid, resource_uid
from app.db.models import Account, Resource
from app.providers.azure.types import canonical_type


def recolectar(ctx: Contexto, session: Session) -> Resultado:
    momento = ctx.momento
    cuentas_uid = {account_uid(s): s for s in ctx.subscription_ids}

    existentes_cuentas = {a.uid: a for a in session.scalars(select(Account).where(Account.uid.in_(cuentas_uid)))}
    for uid, sub_id in cuentas_uid.items():
        cuenta = existentes_cuentas.get(uid)
        nombre = ctx.subscription_names.get(sub_id) or sub_id
        if cuenta is None:
            session.add(Account(uid=uid, provider="azure", native_id=sub_id, name=nombre,
                                first_seen=momento, last_seen=momento))
        else:
            cuenta.name = nombre
            cuenta.last_seen = momento
    session.flush()

    recursos, avisos = ctx.inventory._fetch_all_resources(ctx.subscription_ids, force_refresh=True, strict=True)
    if avisos:
        # Con strict, cualquier aviso es una consulta que no respondio entera.
        raise RuntimeError("Inventario incompleto: " + "; ".join(avisos))

    indice_iac = _indice_iac(ctx)
    creadores = _creadores(ctx)

    existentes: Dict[str, Resource] = {
        r.uid: r for r in session.scalars(select(Resource).where(Resource.account_uid.in_(cuentas_uid)))
    }
    vistos = set()
    nuevos = 0
    for item in recursos:
        uid = resource_uid(item["id"])
        if not item.get("id") or uid in vistos:
            continue
        vistos.add(uid)
        id_lower = item["id"].lower()
        campos = dict(
            name=item.get("name") or "",
            native_type=item.get("type") or "",
            canonical_type=canonical_type(item.get("type") or ""),
            region=item.get("location") or None,
            group_name=item.get("resourceGroup") or None,
            tags=item.get("tags") or {},
            in_iac_state=(id_lower in indice_iac) if indice_iac is not None else None,
            last_seen=momento,
            deleted_at=None,
        )
        recurso = existentes.get(uid)
        if recurso is None:
            nuevos += 1
            session.add(Resource(uid=uid, provider="azure", account_uid=account_uid(item.get("subscriptionId", "")),
                                 first_seen=momento, created_by=creadores.get(id_lower), **campos))
        else:
            for clave, valor in campos.items():
                setattr(recurso, clave, valor)
            # El historial de actividad solo cubre ~14 dias: no se borra un
            # creador conocido porque ya no aparezca.
            if creadores.get(id_lower):
                recurso.created_by = creadores[id_lower]

    bajas = 0
    for uid, recurso in existentes.items():
        if uid not in vistos and recurso.deleted_at is None:
            recurso.deleted_at = momento
            bajas += 1

    return Resultado(items=len(vistos), detail={
        "accounts": len(cuentas_uid), "new": nuevos, "deleted": bajas,
        "iac_index": indice_iac is not None, "known_creators": len(creadores),
    })


def _indice_iac(ctx: Contexto):
    """Ids gestionados por Terraform, o None si no hay estados legibles."""
    tfstate = getattr(ctx.inventory, "_tfstate", None)
    if tfstate is None:
        return None
    try:
        datos = tfstate.get_index()
    except Exception as exc:
        print(f"[recolector] Indice de Terraform no disponible: {exc}")
        return None
    if not datos.get("available"):
        return None
    return {str(i).lower() for i in datos.get("managed_ids") or ()}


def _creadores(ctx: Contexto) -> Dict[str, str]:
    """Quien creo cada recurso creado a mano en la ventana del historial (~14 dias)."""
    try:
        datos = ctx.inventory.get_manual_creations(ctx.subscription_ids, limit=100_000)
    except Exception as exc:
        print(f"[recolector] Historial de creaciones no disponible: {exc}")
        return {}
    return {
        str(m["id"]).lower(): m["createdBy"]
        for m in datos.get("manualCreations") or []
        if m.get("id") and m.get("createdBy")
    }

"""
Recolector de clasificacion ISO 27001 de activos (app/compliance/classification.py).

Corre despues del inventario. Para cada recurso activo:

- Sin clasificacion: se crea la automatica.
- Automatica: se recalcula (cambian las tags, cambia la clasificacion).
- Manual: no se toca; solo se refresca el custodio si estaba vacio.

Las clasificaciones de recursos borrados se conservan, igual que el recurso:
explican hallazgos y costos historicos.
"""

from typing import Dict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.common import Contexto, Resultado, account_uid
from app.compliance.classification import clasificar, custodio
from app.db.models import AssetClassification, Resource

ACTOR = "recolector"


def recolectar(ctx: Contexto, session: Session) -> Resultado:
    cuentas = [account_uid(s) for s in ctx.subscription_ids]
    recursos = list(session.scalars(select(Resource).where(
        Resource.account_uid.in_(cuentas), Resource.deleted_at.is_(None))))
    existentes: Dict[str, AssetClassification] = {
        c.resource_uid: c for c in session.scalars(select(AssetClassification))}

    conteo = {"nuevas": 0, "cambiadas": 0, "manuales": 0}
    por_clase: Dict[str, int] = {}
    for r in recursos:
        responsable = custodio(r.tags, r.created_by)
        fila = existentes.get(r.uid)
        if fila is not None and fila.method == "manual":
            conteo["manuales"] += 1
            if not fila.custodian and responsable:
                fila.custodian = responsable
            por_clase[fila.classification] = por_clase.get(fila.classification, 0) + 1
            continue

        c = clasificar(r.native_type, r.tags)
        valores = dict(classification=c.classification, confidentiality=c.confidentiality, integrity=c.integrity,
                       availability=c.availability, risk_required=c.risk_required, custodian=responsable,
                       method="automatica", reason=c.reason)
        if fila is None:
            session.add(AssetClassification(resource_uid=r.uid, updated_by=ACTOR, updated_at=ctx.momento, **valores))
            conteo["nuevas"] += 1
        elif any(getattr(fila, k) != v for k, v in valores.items()):
            if fila.classification != c.classification:
                conteo["cambiadas"] += 1
            for k, v in valores.items():
                setattr(fila, k, v)
            fila.updated_by, fila.updated_at = ACTOR, ctx.momento
        por_clase[c.classification] = por_clase.get(c.classification, 0) + 1

    return Resultado(items=len(recursos), detail={**conteo, "by_class": por_clase})

"""
Recolector de KPIs diarios: la serie que alimenta las tendencias del panel.

Reemplaza al JSONL de HistoryService, que solo se escribia cuando alguien abria
el resumen. Los indicadores de gobernanza salen de InventoryService (los mismos
del panel); los conteos, de la base ya actualizada por los recolectores
anteriores. Corre al final y es idempotente: reescribe los valores del dia.
"""

from decimal import Decimal
from typing import Dict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collectors.common import Contexto, Resultado, account_uid
from app.db.models import Finding, KpiDaily, Resource

GOBERNANZA = {
    "tagCompliancePercentage": "tag_compliance_pct",
    "nonCompliantResources": "non_compliant_resources",
    "shadowItCandidates": "shadow_it_candidates",
    "resourcesWithoutOwnerCandidate": "resources_without_owner",
}


def recolectar(ctx: Contexto, session: Session) -> Resultado:
    hoy = ctx.momento.date()
    cuentas = [account_uid(s) for s in ctx.subscription_ids]
    valores: Dict[tuple, float] = {}

    resumen = ctx.inventory.get_summary(ctx.subscription_ids, force_refresh=False)
    for origen, metrica in GOBERNANZA.items():
        if resumen.get(origen) is not None:
            valores[("all", metrica)] = resumen[origen]

    por_cuenta = session.execute(
        select(Resource.account_uid, func.count()).where(Resource.account_uid.in_(cuentas), Resource.deleted_at.is_(None))
        .group_by(Resource.account_uid)
    ).all()
    for cuenta, n in por_cuenta:
        valores[(cuenta, "resources_total")] = n
    valores[("all", "resources_total")] = sum(n for _, n in por_cuenta)

    for severidad in ("critica", "alta", "media"):
        valores[("all", f"findings_open_{severidad}")] = session.scalar(
            select(func.count()).select_from(Finding).where(
                Finding.account_uid.in_(cuentas), Finding.status.in_(("abierto", "asumido")), Finding.severity == severidad)
        ) or 0

    existentes = {(k.scope, k.metric): k for k in session.scalars(select(KpiDaily).where(KpiDaily.day == hoy))}
    for (alcance, metrica), valor in valores.items():
        decimal = Decimal(str(round(float(valor), 4)))
        fila = existentes.get((alcance, metrica))
        if fila is None:
            session.add(KpiDaily(day=hoy, scope=alcance, metric=metrica, value=decimal))
        else:
            fila.value = decimal
    return Resultado(items=len(valores), detail={"day": hoy.isoformat()})

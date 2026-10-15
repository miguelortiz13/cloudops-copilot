"""
Reporte de inventario multinube (Reportes): qué hay en cada nube y cuenta,
de qué tipo, dónde, cuánto cuesta y si está en Terraform.

Sale de la base que llena el recolector diario; el recolector lo deja
precalculado (service.precalentar), así que abrirlo no despierta la base.
"""

from datetime import timedelta
from typing import Any, Dict, List

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.compliance.classification import ambiente
from app.db.models import Account, AssetClassification, CostDaily, Finding, Resource
from app.readmodel.cuentas import ETIQUETA, _iso, _ultima

DIAS_DE_COSTO = 30
ACTIVOS = ("abierto", "asumido")


def _contar(valores) -> List[Dict[str, Any]]:
    conteo: Dict[str, int] = {}
    for v in valores:
        conteo[v] = conteo.get(v, 0) + 1
    return [{"key": k, "count": n} for k, n in sorted(conteo.items(), key=lambda kv: (-kv[1], kv[0]))]


def reporte(s: Session) -> Dict[str, Any]:
    cuentas = {c.uid: c for c in s.scalars(select(Account))}
    filas = s.execute(select(Resource, AssetClassification.classification).outerjoin(
        AssetClassification, AssetClassification.resource_uid == Resource.uid).where(Resource.deleted_at.is_(None))).all()

    hasta = s.scalar(select(func.max(CostDaily.charge_date)))
    gasto: Dict[str, float] = {}
    moneda: Dict[str, str] = {}
    gasto_cuenta: Dict[str, float] = {}
    if hasta:
        desde = hasta - timedelta(days=DIAS_DE_COSTO)
        for uid, cuenta, monto, mon in s.execute(
                select(CostDaily.resource_uid, CostDaily.account_uid, func.sum(CostDaily.billed_cost), func.max(CostDaily.currency))
                .where(CostDaily.charge_date > desde).group_by(CostDaily.resource_uid, CostDaily.account_uid)).all():
            gasto_cuenta[cuenta] = gasto_cuenta.get(cuenta, 0.0) + float(monto or 0)
            moneda[cuenta] = mon
            if uid:
                gasto[uid] = gasto.get(uid, 0.0) + float(monto or 0)
    hallazgos = dict(s.execute(select(Finding.account_uid, func.count()).where(Finding.status.in_(ACTIVOS))
                               .group_by(Finding.account_uid)).all())

    recursos = []
    for r, clase in filas:
        c = cuentas.get(r.account_uid)
        recursos.append({
            "uid": r.uid, "provider": r.provider, "account_uid": r.account_uid, "account": c.name if c else r.account_uid,
            "name": r.name, "type": r.canonical_type or r.native_type, "native_type": r.native_type,
            "region": r.region, "group": r.group_name, "environment": ambiente(r.tags) or None,
            "classification": clase, "cost_30d": round(gasto[r.uid], 2) if r.uid in gasto else None,
            "currency": moneda.get(r.account_uid), "in_iac": r.in_iac_state, "created_by": r.created_by,
            "first_seen": _iso(r.first_seen),
        })
    recursos.sort(key=lambda x: (x["provider"], x["account"].lower(), -(x["cost_30d"] or 0), x["name"].lower()))

    por_cuenta = []
    for uid, c in sorted(cuentas.items(), key=lambda kv: (kv[1].provider, kv[1].name.lower())):
        propios = [x for x in recursos if x["account_uid"] == uid]
        if not propios and uid not in gasto_cuenta:
            continue
        por_cuenta.append({
            "uid": uid, "provider": c.provider, "name": c.name, "native_id": c.native_id, "resources": len(propios),
            "cost_30d": round(gasto_cuenta[uid], 2) if uid in gasto_cuenta else None, "currency": moneda.get(uid),
            "open_findings": hallazgos.get(uid, 0), "by_type": _contar(x["type"] for x in propios)[:5],
        })

    proveedores = []
    for nombre in sorted({x["provider"] for x in por_cuenta}):
        propios = [x for x in recursos if x["provider"] == nombre]
        con_gasto = [x for x in por_cuenta if x["provider"] == nombre and x["cost_30d"] is not None]
        corrida = _ultima(s, "inventory" if nombre == "azure" else f"inventory_{nombre}")
        proveedores.append({
            "name": nombre, "label": ETIQUETA.get(nombre, nombre),
            "accounts": sum(1 for x in por_cuenta if x["provider"] == nombre), "resources": len(propios),
            # Sin cuentas con dato de costos es desconocido, no cero.
            "cost_30d": round(sum(x["cost_30d"] for x in con_gasto), 2) if con_gasto else None,
            "currency": next((x["currency"] for x in con_gasto if x["currency"]), None),
            "open_findings": sum(x["open_findings"] for x in por_cuenta if x["provider"] == nombre),
            "in_iac": sum(1 for x in propios if x["in_iac"] is True),
            "iac_known": any(x["in_iac"] is not None for x in propios),
            "by_type": _contar(x["type"] for x in propios)[:8],
            "by_region": _contar(x["region"] or "global" for x in propios)[:8],
            "inventory_at": _iso(corrida.finished_at) if corrida else None,
        })

    return {
        "configured": True, "cost_days": DIAS_DE_COSTO, "cost_until": hasta.isoformat() if hasta else None,
        "providers": proveedores, "accounts": por_cuenta, "resources": recursos,
    }

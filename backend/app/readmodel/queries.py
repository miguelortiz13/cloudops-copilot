"""
Consultas de las vistas del panel sobre el modelo canonico.

Funciones puras sobre una `Session`: las usan el API (si no hay cache) y el
recolector (para precalcular). Devuelven JSON listo para el panel.
"""

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Account, CollectorRun, CostDaily, Finding, FindingEvent, KpiDaily, Resource, Rule

PERIODOS = ("7d", "30d", "90d", "mtd", "last_month")
# Las vistas que el recolector deja calculadas cada dia.
PERIODOS_POR_DEFECTO = ("30d", "mtd", "last_month")
DIAS_KPI_POR_DEFECTO = 90


class PeriodoInvalido(ValueError):
    pass


def _f(valor: Optional[Decimal]) -> float:
    return round(float(valor or 0), 6)


def _ultima_ejecucion(s: Session, recolector: str) -> Optional[str]:
    fin = s.scalar(select(func.max(CollectorRun.finished_at)).where(
        CollectorRun.collector == recolector, CollectorRun.status.in_(("ok", "parcial"))))
    return fin.isoformat() if fin else None


def _cobertura_de_costos(s: Session) -> Optional[date]:
    """
    Desde que dia cubre la base el gasto: el inicio de la ventana mas antigua
    que el recolector leyo con exito. No es la primera fila con gasto: un dia
    sin gasto no deja filas y aun asi esta medido (su costo es cero).
    """
    desdes = [d.get("since") for d in s.scalars(select(CollectorRun.detail).where(
        CollectorRun.collector == "costs", CollectorRun.status.in_(("ok", "parcial")))) if d and d.get("since")]
    return date.fromisoformat(min(desdes)) if desdes else None


def _mes_anterior(d: date) -> date:
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


def rango(periodo: str, hasta: date) -> Tuple[date, date, date, date, str]:
    """(desde, hasta, desde_anterior, hasta_anterior, etiqueta), fechas inclusivas."""
    if periodo in ("7d", "30d", "90d"):
        n = int(periodo[:-1])
        desde = hasta - timedelta(days=n - 1)
        return desde, hasta, desde - timedelta(days=n), desde - timedelta(days=1), f"Últimos {n} días"
    if periodo == "mtd":
        desde = hasta.replace(day=1)
        previo = _mes_anterior(hasta)
        # Los mismos dias del mes anterior (acotado a su ultimo dia).
        fin_previo = previo.replace(day=min(hasta.day, monthrange(previo.year, previo.month)[1]))
        return desde, hasta, previo, fin_previo, "Mes en curso"
    if periodo == "last_month":
        desde = _mes_anterior(hasta)
        fin = hasta.replace(day=1) - timedelta(days=1)
        previo = _mes_anterior(desde)
        return desde, fin, previo, desde - timedelta(days=1), "Mes anterior"
    raise PeriodoInvalido(f"Periodo desconocido: {periodo}. Opciones: {', '.join(PERIODOS)}")


def costos(s: Session, periodo: str = "30d") -> Dict[str, Any]:
    hasta_datos = s.scalar(select(func.max(CostDaily.charge_date)))
    if hasta_datos is None:
        return {"available": False, "message": "Todavía no hay costos recolectados.", "period": periodo}

    desde, hasta, desde_ant, hasta_ant, etiqueta = rango(periodo, hasta_datos)

    def total(a: date, b: date) -> float:
        return _f(s.scalar(select(func.sum(CostDaily.billed_cost)).where(CostDaily.charge_date.between(a, b))))

    actual, anterior = total(desde, hasta), total(desde_ant, hasta_ant)
    en_periodo = CostDaily.charge_date.between(desde, hasta)

    diario = {d: _f(c) for d, c in s.execute(
        select(CostDaily.charge_date, func.sum(CostDaily.billed_cost)).where(en_periodo).group_by(CostDaily.charge_date))}
    serie = []
    d = desde
    while d <= hasta:
        serie.append({"date": d.isoformat(), "cost": diario.get(d, 0.0)})
        d += timedelta(days=1)

    def grupos(columna, limite: Optional[int] = None) -> List[Dict[str, Any]]:
        q = (select(columna, func.sum(CostDaily.billed_cost).label("c")).where(en_periodo)
             .group_by(columna).order_by(func.sum(CostDaily.billed_cost).desc()))
        if limite:
            q = q.limit(limite)
        return [{"key": k or "", "cost": _f(c), "share": round(_f(c) / actual * 100, 2) if actual else 0.0}
                for k, c in s.execute(q)]

    nombres_cuenta = dict(s.execute(select(Account.uid, Account.name)).all())
    por_cuenta = [{**g, "name": nombres_cuenta.get(g["key"], g["key"])} for g in grupos(CostDaily.account_uid)]

    top = grupos(CostDaily.resource_uid, 15)
    recursos = {r.uid: r for r in s.scalars(select(Resource).where(Resource.uid.in_([g["key"] for g in top if g["key"]])))}
    por_recurso = []
    for g in top:
        r = recursos.get(g["key"])
        por_recurso.append({
            **g,
            "name": r.name if r else (g["key"].rsplit("/", 1)[-1] or "Cargos sin recurso"),
            "type": r.native_type if r else None,
            "group": r.group_name if r else None,
            "account": nombres_cuenta.get(r.account_uid) if r else None,
            "deleted": bool(r and r.deleted_at),
        })

    # Totales por mes de los ultimos 13 meses: base del grafico mes a mes.
    inicio_meses = hasta_datos.replace(day=1)
    for _ in range(12):
        inicio_meses = _mes_anterior(inicio_meses)
    meses: Dict[str, float] = {}
    for dia, c in s.execute(select(CostDaily.charge_date, func.sum(CostDaily.billed_cost))
                            .where(CostDaily.charge_date >= inicio_meses).group_by(CostDaily.charge_date)):
        meses[dia.strftime("%Y-%m")] = meses.get(dia.strftime("%Y-%m"), 0.0) + _f(c)

    moneda = s.scalar(select(CostDaily.currency).limit(1)) or "USD"
    primero = _cobertura_de_costos(s) or s.scalar(select(func.min(CostDaily.charge_date)))
    completo = bool(primero and primero <= desde_ant)
    return {
        "available": True,
        "period": periodo,
        "label": etiqueta,
        "from": desde.isoformat(),
        "to": hasta.isoformat(),
        "previous_from": desde_ant.isoformat(),
        "previous_to": hasta_ant.isoformat(),
        # Si la base no cubre el periodo anterior completo, la comparacion no vale.
        "previous_complete": completo,
        "currency": moneda,
        "total": round(actual, 2),
        "previous_total": round(anterior, 2),
        "delta_percentage": round((actual - anterior) / anterior * 100, 1) if anterior and completo else None,
        "daily": serie,
        "by_service": grupos(CostDaily.service_name),
        "by_account": por_cuenta,
        "by_resource": por_recurso,
        "by_month": [{"month": m, "cost": round(c, 2)} for m, c in sorted(meses.items())],
        "data_from": primero.isoformat() if primero else None,
        "data_through": hasta_datos.isoformat(),
        "collected_at": _ultima_ejecucion(s, "costs"),
    }


def _hallazgo(f: Finding, regla: Optional[Rule], recurso: Optional[Resource], cuenta: Optional[str]) -> Dict[str, Any]:
    detalle = f.details or {}
    return {
        "id": f.id,
        "rule_id": f.rule_id,
        "title": regla.title if regla else f.rule_id,
        "remediation": regla.remediation if regla else None,
        "severity": f.severity,
        "status": f.status,
        "resource_uid": f.resource_uid,
        "resource_name": (recurso.name if recurso else None) or detalle.get("name") or f.resource_uid.rsplit("/", 1)[-1],
        "resource_type": recurso.native_type if recurso else detalle.get("type"),
        "resource_group": (recurso.group_name if recurso else None) or detalle.get("resourceGroup"),
        "account": cuenta,
        "details": detalle,
        "owner": f.owner,
        "due_date": f.due_date.isoformat() if f.due_date else None,
        "accepted_until": f.accepted_until.isoformat() if f.accepted_until else None,
        "first_seen": f.first_seen.isoformat(),
        "last_seen": f.last_seen.isoformat(),
        "resolved_at": f.resolved_at.isoformat() if f.resolved_at else None,
    }


def hallazgos(s: Session) -> Dict[str, Any]:
    reglas = {r.id: r for r in s.scalars(select(Rule))}
    cuentas = dict(s.execute(select(Account.uid, Account.name)).all())
    filas = list(s.scalars(select(Finding)))
    # Un NSG con varias reglas: el recurso del inventario es el NSG.
    uids = {f.resource_uid.split("/securityrules/")[0] for f in filas}
    recursos = {r.uid: r for r in s.scalars(select(Resource).where(Resource.uid.in_(uids)))} if uids else {}
    items = [_hallazgo(f, reglas.get(f.rule_id), recursos.get(f.resource_uid.split("/securityrules/")[0]),
                       cuentas.get(f.account_uid)) for f in filas]
    orden = {"critica": 0, "alta": 1, "media": 2}
    items.sort(key=lambda h: (h["status"] == "resuelto", orden.get(h["severity"], 9), h["first_seen"]))
    conteo: Dict[str, int] = {}
    for h in items:
        conteo[h["status"]] = conteo.get(h["status"], 0) + 1
    return {"available": True, "items": items, "by_status": conteo, "collected_at": _ultima_ejecucion(s, "findings")}


def eventos(s: Session, hallazgo_id: int) -> List[Dict[str, Any]]:
    return [{"at": e.at.isoformat(), "kind": e.kind, "from": e.from_status, "to": e.to_status,
             "actor": e.actor, "note": e.note}
            for e in s.scalars(select(FindingEvent).where(FindingEvent.finding_id == hallazgo_id)
                               .order_by(FindingEvent.at, FindingEvent.id))]


def kpis(s: Session, dias: int = DIAS_KPI_POR_DEFECTO) -> Dict[str, Any]:
    ultimo = s.scalar(select(func.max(KpiDaily.day)))
    if ultimo is None:
        return {"available": False, "metrics": {}, "points": 0}
    desde = ultimo - timedelta(days=dias - 1)
    series: Dict[str, List[Dict[str, Any]]] = {}
    for k in s.scalars(select(KpiDaily).where(KpiDaily.scope == "all", KpiDaily.day >= desde).order_by(KpiDaily.day)):
        series.setdefault(k.metric, []).append({"day": k.day.isoformat(), "value": float(k.value)})
    return {"available": True, "metrics": series, "points": len({p["day"] for v in series.values() for p in v}),
            "from": desde.isoformat(), "to": ultimo.isoformat(), "collected_at": _ultima_ejecucion(s, "kpis")}

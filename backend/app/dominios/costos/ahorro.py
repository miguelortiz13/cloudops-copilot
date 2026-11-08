"""
Ahorro realizado (fase 4 del plan 10): lo que de verdad se dejó de gastar, no lo que se estimó.

- **Aplicadas**: oportunidades que una persona marcó como aplicadas desde Costos → Ahorro, con el ahorro que
  esperaba. Quedan *pendientes* mientras el recurso siga en el inventario y se *verifican* solas cuando
  desaparece: el ahorro realizado es su gasto real de los 30 días previos a la baja.
- **Bajas**: cualquier recurso que dejó de estar en el inventario en el periodo, con el gasto de sus 30 días
  previos (el gasto mensual que se evitó, haya pasado o no por el panel).
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import func, select

from app.db import engine as db
from app.db.models import CostDaily, Resource, SavingAction

DIAS_PREVIOS = 30


def _gasto_previo(s, uid: str, hasta: datetime) -> float:
    fin = hasta.date()
    return float(s.scalar(select(func.sum(CostDaily.billed_cost)).where(
        CostDaily.resource_uid == uid, CostDaily.charge_date > fin - timedelta(days=DIAS_PREVIOS),
        CostDaily.charge_date <= fin)) or 0)


def aplicar(uid: str, nombre: str, categoria: str, esperado: float, nota: Optional[str], actor: str) -> Dict[str, Any]:
    with db.session_scope() as s:
        a = SavingAction(resource_uid=uid[:450], name=nombre[:260], category=categoria[:100], expected_monthly=max(float(esperado), 0.0),
                         note=(nota or "").strip()[:2000] or None, applied_by=actor, applied_at=datetime.now(timezone.utc))
        s.add(a)
        s.flush()
        return {"id": a.id, "resource_uid": a.resource_uid, "status": "pendiente"}


def realizado(dias: int = 90, ahora: Optional[datetime] = None) -> Dict[str, Any]:
    desde = (ahora or datetime.now(timezone.utc)) - timedelta(days=dias)
    with db.session_scope() as s:
        aplicadas = []
        for a in s.scalars(select(SavingAction).order_by(SavingAction.applied_at.desc()).limit(300)):
            r = s.get(Resource, a.resource_uid)
            baja = r.deleted_at if r is not None else None
            aplicadas.append({
                "id": a.id, "resource_uid": a.resource_uid, "name": a.name, "category": a.category,
                "expected_monthly": round(a.expected_monthly, 2), "applied_by": a.applied_by, "applied_at": a.applied_at.isoformat(),
                "note": a.note, "status": "verificado" if baja else "pendiente", "removed_at": baja.isoformat() if baja else None,
                "realized_monthly": round(_gasto_previo(s, a.resource_uid, baja), 2) if baja else None,
            })
        bajas = []
        for r in s.scalars(select(Resource).where(Resource.deleted_at >= desde).order_by(Resource.deleted_at.desc()).limit(500)):
            gasto = _gasto_previo(s, r.uid, r.deleted_at)
            if gasto > 0:
                bajas.append({"uid": r.uid, "name": r.name, "provider": r.provider, "type": r.canonical_type or r.native_type,
                              "removed_at": r.deleted_at.isoformat(), "monthly_before": round(gasto, 2)})
    verificadas = [a for a in aplicadas if a["status"] == "verificado"]
    return {
        "days": dias, "applied": aplicadas, "removed": bajas,
        "totals": {"applied_pending": sum(1 for a in aplicadas if a["status"] == "pendiente"),
                   "expected_monthly": round(sum(a["expected_monthly"] for a in aplicadas), 2),
                   "realized_monthly": round(sum(a["realized_monthly"] or 0 for a in verificadas), 2),
                   "removed_monthly": round(sum(b["monthly_before"] for b in bajas), 2)},
    }

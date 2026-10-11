"""
Recolector de costos: gasto diario por recurso y servicio (FOCUS, ADR 0008).

Cost Management consolida el gasto de los ultimos dias durante unas 72 horas,
asi que cada ejecucion reemplaza una ventana movil en lugar de agregar solo el
dia anterior. La primera ejecucion trae un año.

Columnas FOCUS: `billed_cost` es el costo real facturado (ActualCost). Sin
reservas ni planes de ahorro coincide con `effective_cost`; cuando existan, el
costo efectivo vendra de los exports FOCUS (fase 1, costos desde la base).
"""

from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.collectors.common import Contexto, Resultado
from app.db.models import CollectorRun, CostDaily

# Carga inicial: un año, para que la comparacion mes a mes funcione desde el
# primer dia. Es el maximo de una consulta de Cost Management, contando el dia
# final (365 dias falla con "cannot exceed 1 year").
DIAS_INICIALES = 364
DIAS_MOVILES = 7
FUENTE = "query"


def recolectar(ctx: Contexto, session: Session) -> Resultado:
    # Ventana movil si alguna recoleccion ya hizo la carga inicial completa;
    # las filas no sirven de señal porque una cuenta sin gasto nunca tiene filas.
    previas = session.scalars(select(CollectorRun.detail).where(
        CollectorRun.collector == "costs", CollectorRun.status.in_(("ok", "parcial"))))
    carga_hecha = any((d or {}).get("window_days", 0) >= DIAS_INICIALES for d in previas)
    dias = DIAS_MOVILES if carga_hecha else DIAS_INICIALES

    resultado = ctx.proveedor.costos_diarios(ctx.cuentas_uid, dias)
    cobertura = resultado.cobertura
    cubiertas = list(cobertura.cubiertas)
    if not cubiertas:
        raise RuntimeError(f"El proveedor no entrego costos de ninguna cuenta (denegadas: {cobertura.denegadas}, "
                           f"fallidas: {cobertura.fallidas}).")

    desde = ctx.momento.date() - timedelta(days=dias)
    # Solo se reemplaza la ventana de las cuentas cubiertas: de las demas se
    # conserva lo que ya habia (el proveedor solo entrega filas de las cubiertas).
    for cuenta in cubiertas:
        session.execute(delete(CostDaily).where(
            CostDaily.account_uid == cuenta, CostDaily.source == FUENTE, CostDaily.charge_date >= desde,
        ))
    filas = [f for f in resultado.filas if f.charge_date >= desde and f.account_uid in cubiertas]
    for f in filas:
        session.add(CostDaily(charge_date=f.charge_date, account_uid=f.account_uid, resource_uid=f.resource_uid,
                              service_name=f.service_name, billed_cost=f.billed_cost, effective_cost=f.effective_cost,
                              currency=f.currency, source=FUENTE))
    session.flush()

    total = session.scalar(select(func.coalesce(func.sum(CostDaily.billed_cost), 0)).where(
        CostDaily.account_uid.in_(cubiertas), CostDaily.charge_date >= desde))
    faltantes = cobertura.denegadas + cobertura.fallidas
    return Resultado(
        items=len(filas),
        status="parcial" if faltantes else "ok",
        detail={"window_days": dias, "since": desde.isoformat(), "covered": len(cubiertas),
                "denied": cobertura.denegadas, "failed": cobertura.fallidas,
                "recovered_on_retry": cobertura.recuperadas, "total": float(total or 0)},
    )

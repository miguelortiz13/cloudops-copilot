"""
Recolector de costos: gasto diario por recurso y servicio (FOCUS, ADR 0008).

Cost Management consolida el gasto de los ultimos dias durante unas 72 horas,
asi que cada ejecucion reemplaza una ventana movil en lugar de agregar solo el
dia anterior. La primera ejecucion trae un año.

Columnas FOCUS: `billed_cost` es el costo real facturado (ActualCost). Sin
reservas ni planes de ahorro coincide con `effective_cost`; cuando existan, el
costo efectivo vendra de los exports FOCUS (fase 1, costos desde la base).
"""

import time
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.collectors.common import Contexto, Resultado, account_uid, resource_uid
from app.db.models import CollectorRun, CostDaily

# Carga inicial: un año, para que la comparacion mes a mes funcione desde el
# primer dia. Es el maximo de una consulta de Cost Management, contando el dia
# final (365 dias falla con "cannot exceed 1 year").
DIAS_INICIALES = 364
DIAS_MOVILES = 7
FUENTE = "query"
# Cost Management corta con 429 cuando se agota la cuota de la ventana. Las
# suscripciones que fallaron se reintentan una vez, mas despacio, tras esperar
# a que se libere (la misma estrategia que la precarga de costos).
ESPERA_REINTENTO_SEGUNDOS = 60
PAUSA = 2.0


def _consultar(ctx: Contexto, dias: int):
    datos = ctx.cost.get_daily_cost_by_resource(ctx.subscription_ids, days=dias, pace_seconds=PAUSA)
    cobertura = {k: list(v) for k, v in (datos.get("coverage") or {}).items()}
    filas = list(datos.get("rows") or [])
    fallidas = cobertura.get("failed") or []
    if not fallidas:
        return datos, filas, cobertura, 0
    print(f"[recolector] costos: reintentando {len(fallidas)} suscripcion(es) en {ESPERA_REINTENTO_SEGUNDOS:.0f} s.")
    time.sleep(ESPERA_REINTENTO_SEGUNDOS)
    segunda = ctx.cost.get_daily_cost_by_resource(fallidas, days=dias, pace_seconds=PAUSA * 2)
    recuperadas = (segunda.get("coverage") or {}).get("covered") or []
    filas += [f for f in segunda.get("rows") or [] if f.get("subscription_id") in recuperadas]
    cobertura["covered"] = (cobertura.get("covered") or []) + recuperadas
    cobertura["failed"] = [s for s in fallidas if s not in recuperadas]
    cobertura["denied"] = (cobertura.get("denied") or []) + ((segunda.get("coverage") or {}).get("denied") or [])
    return datos, filas, cobertura, len(recuperadas)


def recolectar(ctx: Contexto, session: Session) -> Resultado:
    # Ventana movil si alguna recoleccion ya hizo la carga inicial completa;
    # las filas no sirven de señal porque una cuenta sin gasto nunca tiene filas.
    previas = session.scalars(select(CollectorRun.detail).where(
        CollectorRun.collector == "costs", CollectorRun.status.in_(("ok", "parcial"))))
    carga_hecha = any((d or {}).get("window_days", 0) >= DIAS_INICIALES for d in previas)
    dias = DIAS_MOVILES if carga_hecha else DIAS_INICIALES

    datos, filas_crudas, cobertura, recuperadas = _consultar(ctx, dias)
    cubiertas = list(cobertura.get("covered", []))
    if not cubiertas:
        raise RuntimeError(f"Cost Management no respondio para ninguna suscripcion ({datos.get('status')}).")

    desde = ctx.momento.date() - timedelta(days=dias)
    # Una fila por clave unica: Cost Management puede repetir combinaciones
    # (por ejemplo, el mismo recurso con distinta capitalizacion).
    filas = {}
    # Solo las suscripciones cubiertas: de las demas no se borro la ventana, y
    # sus filas se duplicarian con las que ya estan.
    for f in filas_crudas:
        dia = date.fromisoformat(f["date"])
        if dia < desde or f["subscription_id"] not in cubiertas:
            continue
        clave = (dia, account_uid(f["subscription_id"]), resource_uid(f["resource_id"]) if f["resource_id"] else "",
                 f["service_name"][:200])
        previo = filas.get(clave)
        monto = Decimal(str(round(f["cost"], 6)))
        filas[clave] = (previo[0] + monto, f["currency"]) if previo else (monto, f["currency"])

    for sub_id in cubiertas:
        session.execute(delete(CostDaily).where(
            CostDaily.account_uid == account_uid(sub_id), CostDaily.source == FUENTE, CostDaily.charge_date >= desde,
        ))
    for (dia, cuenta, recurso, servicio), (monto, moneda) in filas.items():
        session.add(CostDaily(charge_date=dia, account_uid=cuenta, resource_uid=recurso, service_name=servicio,
                              billed_cost=monto, effective_cost=monto, currency=moneda[:3], source=FUENTE))
    session.flush()

    total = session.scalar(select(func.coalesce(func.sum(CostDaily.billed_cost), 0)).where(
        CostDaily.account_uid.in_([account_uid(s) for s in cubiertas]), CostDaily.charge_date >= desde))
    faltantes = cobertura.get("denied", []) + cobertura.get("failed", [])
    return Resultado(
        items=len(filas),
        status="parcial" if faltantes else "ok",
        detail={"window_days": dias, "since": desde.isoformat(), "covered": len(cubiertas),
                "denied": cobertura.get("denied", []), "failed": cobertura.get("failed", []),
                "recovered_on_retry": recuperadas, "total": float(total or 0)},
    )

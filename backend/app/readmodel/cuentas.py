"""
Cuentas conectadas (Administración): qué ve la plataforma de cada nube y con
qué permisos efectivos.

Sale de la base, sin consultar la nube: lo que el recolector diario logró
leer es justamente la medida de los permisos efectivos. Una cuenta que dejó
de aparecer en el inventario perdió el acceso; una denegada en costos no
tiene el rol de lectura de costos.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import config
from app.db.models import Account, CollectorRun, CostDaily, Finding, Resource

ETIQUETA = {"azure": "Microsoft Azure", "aws": "Amazon Web Services", "gcp": "Google Cloud"}
# Qué rol falta cuando una cuenta no entrega costos, por proveedor.
ROL_DE_COSTOS = {"azure": "Cost Management Reader"}
DIAS_DE_COSTO = 30


def _iso(momento: Optional[datetime]) -> Optional[str]:
    if momento is None:
        return None
    return (momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)).isoformat()


def _aware(momento: Optional[datetime]) -> Optional[datetime]:
    return momento if momento is None or momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def _ultima(s: Session, recolector: str) -> Optional[CollectorRun]:
    return s.scalars(select(CollectorRun).where(
        CollectorRun.collector == recolector, CollectorRun.status.in_(("ok", "parcial")))
        .order_by(CollectorRun.started_at.desc()).limit(1)).first()


def _identidad() -> Dict[str, Any]:
    if config.AZURE_MANAGED_IDENTITY_CLIENT_ID:
        return {"kind": "identidad_administrada", "client_id": config.AZURE_MANAGED_IDENTITY_CLIENT_ID}
    return {"kind": "credencial_por_defecto", "client_id": None}


def _estado_de_costos(cuenta: Account, corrida: Optional[CollectorRun]) -> str:
    """con_permiso | sin_permiso | fallo | sin_dato."""
    if corrida is None:
        return "sin_dato"
    d = corrida.detail or {}
    # Las ejecuciones anteriores a la capa de proveedores guardaban ids nativos.
    claves = {cuenta.uid, cuenta.native_id, cuenta.native_id.lower()}
    if claves & set(d.get("denied") or []):
        return "sin_permiso"
    if claves & set(d.get("failed") or []):
        return "fallo"
    if "covered_accounts" in d:
        return "con_permiso" if cuenta.uid in d["covered_accounts"] else "sin_dato"
    return "con_permiso"


def cuentas_conectadas(s: Session) -> Dict[str, Any]:
    inventario = _ultima(s, "inventory")
    costos = _ultima(s, "costs")
    cuentas = list(s.scalars(select(Account).order_by(Account.provider, Account.name)))

    recursos = dict(s.execute(select(Resource.account_uid, func.count()).where(Resource.deleted_at.is_(None))
                              .group_by(Resource.account_uid)).all())
    hallazgos = dict(s.execute(select(Finding.account_uid, func.count()).where(Finding.status.in_(("abierto", "asumido")))
                               .group_by(Finding.account_uid)).all())
    hasta = s.scalar(select(func.max(CostDaily.charge_date)))
    gasto: Dict[str, Any] = {}
    if hasta:
        gasto = {c: (float(m or 0), moneda) for c, m, moneda in s.execute(
            select(CostDaily.account_uid, func.sum(CostDaily.billed_cost), func.max(CostDaily.currency))
            .where(CostDaily.charge_date > hasta - timedelta(days=DIAS_DE_COSTO)).group_by(CostDaily.account_uid)).all()}

    # Una cuenta es visible si apareció en la última recolección de inventario:
    # su last_seen es el momento con el que esa recolección marcó las cuentas
    # (anterior al inicio registrado de la ejecución, así que no sirve como corte).
    desde_ultima = None
    if inventario:
        marca = (inventario.detail or {}).get("seen_at")
        desde_ultima = _aware(datetime.fromisoformat(marca)) if marca else max(
            (_aware(c.last_seen) for c in cuentas), default=None)
    items: List[Dict[str, Any]] = []
    for c in cuentas:
        visible = bool(desde_ultima and _aware(c.last_seen) >= desde_ultima)
        estado_costos = _estado_de_costos(c, costos)
        monto, moneda = gasto.get(c.uid, (None, None))
        if monto is None and estado_costos == "con_permiso":
            # Cubierta y sin filas: Cost Management respondió y no hubo gasto. Es cero, no desconocido.
            monto = 0.0
        items.append({
            "uid": c.uid, "provider": c.provider, "native_id": c.native_id, "name": c.name, "parent": c.parent,
            "first_seen": _iso(c.first_seen), "last_seen": _iso(c.last_seen), "visible": visible,
            "resources": recursos.get(c.uid, 0), "open_findings": hallazgos.get(c.uid, 0),
            "cost_30d": round(monto, 2) if monto is not None else None, "currency": moneda,
            "cost_status": estado_costos,
        })

    detalle = (inventario.detail or {}) if inventario else {}
    proveedores = []
    for nombre in sorted({c.provider for c in cuentas} | ({detalle["provider"]} if detalle.get("provider") else set())):
        propias = [i for i in items if i["provider"] == nombre]
        es_el_de_la_corrida = detalle.get("provider", "azure") == nombre
        proveedores.append({
            "name": nombre,
            "label": ETIQUETA.get(nombre, nombre),
            "capabilities": detalle.get("capabilities") if es_el_de_la_corrida else None,
            "unavailable": detalle.get("unavailable", {}) if es_el_de_la_corrida else {},
            "identity": _identidad() if nombre == "azure" else None,
            "cost_role": ROL_DE_COSTOS.get(nombre),
            "accounts": len(propias),
            "visible": sum(1 for i in propias if i["visible"]),
            "cost_denied": sum(1 for i in propias if i["cost_status"] == "sin_permiso"),
        })

    return {
        "configured": True,
        "inventory_at": _iso(inventario.finished_at) if inventario else None,
        "costs_at": _iso(costos.finished_at) if costos else None,
        "cost_days": DIAS_DE_COSTO,
        "providers": proveedores,
        "accounts": items,
    }

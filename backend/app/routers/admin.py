"""
Administracion de la plataforma.

`/api/admin/database` abre una conexion: despierta la base si esta pausada y
consume cupo durante la hora siguiente. Por eso no forma parte del health
check ni de ninguna sonda; se consulta solo cuando alguien lo pide.
"""

from fastapi import APIRouter, HTTPException

from app.core.authz import requiere
from sqlalchemy import func, inspect, select, text

from app.db import engine as db
from app.db.models import AuditLog, Base, CollectorRun

# Todo lo de administracion es para el rol administrador.
router = APIRouter(tags=["admin"], dependencies=[requiere("administrador")])


@router.get("/api/admin/database")
def database_status():
    if not db.is_configured():
        return {"configured": False, "message": "Sin base de datos: la plataforma responde en vivo."}
    try:
        with db.connect() as c:
            existentes = set(inspect(c).get_table_names())
            # Una base sin migrar no tiene alembic_version: se informa, no se cae.
            revision = (c.execute(text("SELECT version_num FROM alembic_version")).scalar()
                        if "alembic_version" in existentes else None)
            filas = {
                nombre: c.execute(select(func.count()).select_from(tabla)).scalar() if nombre in existentes else None
                for nombre, tabla in sorted(Base.metadata.tables.items())
            }
            ultimas = c.execute(
                select(CollectorRun.collector, CollectorRun.status, CollectorRun.started_at,
                       CollectorRun.finished_at, CollectorRun.items)
                .order_by(CollectorRun.started_at.desc()).limit(10)
            ).all()
    except db.DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        "configured": True,
        "dialect": db.get_engine().dialect.name,
        "revision": revision,
        "rows": filas,
        "recent_runs": [dict(r._mapping) for r in ultimas],
    }


@router.get("/api/admin/audit")
def audit_log(limit: int = 100):
    """Ultimas acciones auditadas (abre la base)."""
    if not db.is_configured():
        return {"configured": False, "items": []}
    try:
        with db.session_scope() as s:
            filas = s.scalars(select(AuditLog).order_by(AuditLog.at.desc()).limit(min(max(limit, 1), 500))).all()
            items = [{"at": a.at.isoformat(), "actor": a.actor, "role": a.role, "action": a.action,
                      "target": a.target, "outcome": a.outcome, "detail": a.detail} for a in filas]
    except db.DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"configured": True, "items": items}

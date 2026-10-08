"""
Administracion de la plataforma.

`/api/admin/database` abre una conexion: despierta la base si esta pausada y
consume cupo durante la hora siguiente. Por eso no forma parte del health
check ni de ninguna sonda; se consulta solo cuando alguien lo pide.
"""

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select, text

from app.db import engine as db
from app.db.models import Base, CollectorRun

router = APIRouter(tags=["admin"])


@router.get("/api/admin/database")
def database_status():
    if not db.is_configured():
        return {"configured": False, "message": "Sin base de datos: la plataforma responde en vivo."}
    try:
        with db.connect() as c:
            revision = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
            filas = {
                nombre: c.execute(select(func.count()).select_from(tabla)).scalar()
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

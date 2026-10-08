"""
Entorno de Alembic.

La conexion es la misma del API (app.db.engine): Azure SQL con Entra ID, o
DATABASE_URL. Incluye la espera a que una base serverless pausada se reanude.

    alembic upgrade head                       # base configurada en el entorno
    DATABASE_URL=sqlite:///x.db alembic upgrade head
"""

from alembic import context

from app.db import engine as db
from app.db.models import Base

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=db.database_url(), target_metadata=target_metadata, literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with db.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

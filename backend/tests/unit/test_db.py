"""
Capa de datos (app/db) sin Azure: SQLite en un directorio temporal.

- La migracion crea exactamente el modelo (sin desfase entre models.py y
  migrations/).
- La URL de Azure SQL usa identidad administrada en Azure y `az login` en
  desarrollo, nunca contraseña.
- `connect()` espera a una base serverless que se reanuda, y no reintenta
  errores que no se arreglan esperando.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import inspect  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402

from app.core import config  # noqa: E402
from app.db import engine as db  # noqa: E402
from app.db.models import Base  # noqa: E402

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def base_sqlite(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'cloudops.db'}")
    db.reset_engine()
    yield
    db.reset_engine()


def _alembic() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return cfg


def test_la_migracion_crea_el_modelo_completo(base_sqlite):
    command.upgrade(_alembic(), "head")
    with db.connect() as c:
        tablas = set(inspect(c).get_table_names())
    assert tablas == set(Base.metadata.tables) | {"alembic_version"}
    # `alembic check` falla si models.py cambio sin una migracion nueva.
    command.check(_alembic())


def test_url_con_identidad_administrada(monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", "")
    monkeypatch.setattr(config, "DB_SERVER", "sql-x.database.windows.net")
    monkeypatch.setattr(config, "DB_NAME", "sqldb-x")
    monkeypatch.setattr(config, "AZURE_MANAGED_IDENTITY_CLIENT_ID", "11111111-2222-3333-4444-555555555555")
    url = db.database_url()
    assert url.drivername == "mssql+mssqlpython"
    assert url.username == "11111111-2222-3333-4444-555555555555"
    assert url.password is None
    assert url.query["authentication"] == "ActiveDirectoryMSI"
    assert url.query["Encrypt"] == "yes"


def test_url_en_desarrollo_usa_la_sesion_de_az(monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", "")
    monkeypatch.setattr(config, "DB_SERVER", "sql-x.database.windows.net")
    monkeypatch.setattr(config, "DB_NAME", "sqldb-x")
    monkeypatch.setattr(config, "AZURE_MANAGED_IDENTITY_CLIENT_ID", "")
    url = db.database_url()
    assert url.username is None
    assert url.query["authentication"] == "ActiveDirectoryDefault"


def test_sin_configuracion_no_hay_base(monkeypatch):
    for nombre in ("DATABASE_URL", "DB_SERVER", "DB_NAME"):
        monkeypatch.setattr(config, nombre, "")
    assert db.database_url() is None
    with pytest.raises(db.DatabaseUnavailable):
        db.get_engine()


class EngineFalso:
    def __init__(self, errores):
        self.errores = list(errores)
        self.intentos = 0

    def connect(self):
        self.intentos += 1
        if self.errores:
            raise DBAPIError("SELECT 1", {}, Exception(self.errores.pop(0)))
        return "conexion"


def test_espera_a_que_la_base_se_reanude(monkeypatch):
    falso = EngineFalso(["(40613) Database 'x' on server 'y' is not currently available"] * 2)
    monkeypatch.setattr(db, "get_engine", lambda: falso)
    monkeypatch.setattr(db.time, "sleep", lambda s: None)
    assert db.connect(timeout=60) == "conexion"
    assert falso.intentos == 3


def test_no_reintenta_un_error_de_permisos(monkeypatch):
    falso = EngineFalso(["(18456) Login failed for user '<token-identified principal>'"])
    monkeypatch.setattr(db, "get_engine", lambda: falso)
    monkeypatch.setattr(db.time, "sleep", lambda s: pytest.fail("no debia esperar"))
    with pytest.raises(db.DatabaseUnavailable, match="Login failed"):
        db.connect(timeout=60)
    assert falso.intentos == 1


def test_se_rinde_al_vencer_el_plazo(monkeypatch):
    falso = EngineFalso(["(40613) not currently available"] * 100)
    monkeypatch.setattr(db, "get_engine", lambda: falso)
    monkeypatch.setattr(db.time, "sleep", lambda s: None)
    with pytest.raises(db.DatabaseUnavailable):
        db.connect(timeout=0)


def test_estado_de_la_base(base_sqlite):
    from app.main import app

    command.upgrade(_alembic(), "head")
    r = TestClient(app).get("/api/admin/database")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["revision"] == "0001"
    assert cuerpo["rows"]["findings"] == 0
    assert cuerpo["recent_runs"] == []


def test_estado_sin_base(monkeypatch):
    from app.main import app

    for nombre in ("DATABASE_URL", "DB_SERVER", "DB_NAME"):
        monkeypatch.setattr(config, nombre, "")
    assert TestClient(app).get("/api/admin/database").json()["configured"] is False

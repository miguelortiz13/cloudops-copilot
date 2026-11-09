"""La red de tests/conftest.py: una consulta que SQL Server rechaza falla aunque SQLite la acepte."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import create_engine, false, func, select  # noqa: E402

from app.db.models import Base, Resource  # noqa: E402


def test_is_false_falla_aunque_sqlite_lo_acepte_y_la_forma_correcta_pasa():
    motor = create_engine("sqlite://")
    Base.metadata.create_all(motor)
    with motor.connect() as c:
        with pytest.raises(conftest.SqlNoValidoEnSqlServer, match="IS 0"):
            c.execute(select(func.count()).select_from(Resource).where(Resource.in_iac_state.is_(False)))
        assert c.execute(select(func.count()).select_from(Resource).where(Resource.in_iac_state == false())).scalar() == 0


def test_offset_sin_orden_no_compila_para_sql_server():
    with pytest.raises(conftest.SqlNoValidoEnSqlServer, match="no compila"):
        conftest.verificar_en_sql_server(select(Resource.uid).offset(10))

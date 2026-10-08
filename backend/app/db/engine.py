"""
Conexion a la base de datos.

Azure SQL serverless se pausa tras una hora sin conexiones y la primera
conexion posterior falla con el error 40613 mientras se reanuda (hasta un
minuto). `connect()` reintenta solo ese caso, con un limite de tiempo; los
demas errores (permisos, firewall) se informan de inmediato.

Importante para el cupo gratuito: nada en el API debe abrir conexiones de
forma periodica (health checks, sondas, precargas). Cada conexion despierta la
base y consume vCore-segundos durante la hora siguiente.
"""

import threading
import time
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core import config


class DatabaseUnavailable(RuntimeError):
    """La base no esta configurada o no respondio a tiempo."""


# Mensajes de Azure SQL que indican una base reanudandose o un corte
# transitorio. Un error de autenticacion o de firewall no esta aqui: no se
# resuelve esperando.
_TRANSITORIOS = ("40613", "40197", "40501", "49918", "not currently available", "communication link failure")


def database_url() -> Optional[URL | str]:
    """URL de conexion segun la configuracion, o None si no hay base."""
    if config.DATABASE_URL:
        return config.DATABASE_URL
    if not (config.DB_SERVER and config.DB_NAME):
        return None
    query = {"Encrypt": "yes", "TrustServerCertificate": "no"}
    if config.AZURE_MANAGED_IDENTITY_CLIENT_ID:
        # Identidad administrada asignada por el usuario: el client id va en UID.
        query["authentication"] = "ActiveDirectoryMSI"
        usuario = config.AZURE_MANAGED_IDENTITY_CLIENT_ID
    else:
        # Desarrollo: la sesion de `az login` (DefaultAzureCredential).
        query["authentication"] = "ActiveDirectoryDefault"
        usuario = None
    return URL.create(
        "mssql+mssqlpython", username=usuario, host=config.DB_SERVER, port=1433,
        database=config.DB_NAME, query=query,
    )


def is_configured() -> bool:
    return database_url() is not None


_engine: Optional[Engine] = None
_lock = threading.Lock()


def get_engine() -> Engine:
    global _engine
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is None:
            url = database_url()
            if url is None:
                raise DatabaseUnavailable("La base de datos no esta configurada (DB_SERVER/DB_NAME o DATABASE_URL).")
            # pool_pre_ping descarta conexiones que murieron con una pausa.
            _engine = create_engine(url, pool_pre_ping=True, pool_recycle=1800)
    return _engine


def reset_engine() -> None:
    """Olvida el engine (pruebas o cambio de configuracion)."""
    global _engine
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None


def _es_transitorio(exc: Exception) -> bool:
    texto = str(exc).lower()
    return any(marca in texto for marca in _TRANSITORIOS)


def connect(timeout: Optional[float] = None) -> Connection:
    """Abre una conexion esperando, si hace falta, a que la base se reanude."""
    engine = get_engine()
    limite = time.monotonic() + (config.DB_RESUME_TIMEOUT_SECONDS if timeout is None else timeout)
    espera = 2.0
    while True:
        try:
            return engine.connect()
        except DBAPIError as exc:
            if not _es_transitorio(exc) or time.monotonic() + espera > limite:
                raise DatabaseUnavailable(f"No se pudo conectar a la base: {str(exc).splitlines()[0]}") from exc
            print(f"[db] La base se esta reanudando; reintento en {espera:.0f}s.")
            time.sleep(espera)
            espera = min(espera * 2, 15)


@contextmanager
def session_scope(timeout: Optional[float] = None) -> Iterator[Session]:
    """Sesion transaccional: confirma al salir, revierte ante un error."""
    connection = connect(timeout)
    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        connection.close()

"""Cache en disco de las lecturas, valida hasta la siguiente recoleccion."""

import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from app.core import config

# Hora UTC a partir de la cual se espera una recoleccion nueva. El recolector
# corre a las 06:00 y tarda minutos; una hora de margen.
HORA_RENOVACION = int(os.getenv("READMODEL_REFRESH_HOUR_UTC", "7"))


def directorio() -> Path:
    return Path(config.DATA_DIR) / "readmodel"


def proxima_renovacion(ahora: Optional[datetime] = None) -> datetime:
    ahora = ahora or datetime.now(timezone.utc)
    hoy = ahora.replace(hour=HORA_RENOVACION, minute=0, second=0, microsecond=0)
    return hoy if ahora < hoy else hoy + timedelta(days=1)


def clave(nombre: str, **params: Any) -> str:
    return f"{nombre}:" + json.dumps(params, sort_keys=True, default=str)


def _ruta(llave: str) -> Path:
    return directorio() / (hashlib.sha1(llave.encode()).hexdigest() + ".json")


def leer(llave: str) -> Optional[Any]:
    try:
        contenido = json.loads(_ruta(llave).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if contenido.get("key") != llave or contenido.get("expires", 0) < time.time():
        return None
    return contenido.get("data")


def guardar(llave: str, datos: Any, expira: Optional[datetime] = None) -> None:
    """Escritura atomica: el API y el recolector comparten el directorio."""
    expira = expira or proxima_renovacion()
    try:
        directorio().mkdir(parents=True, exist_ok=True)
        fd, temporal = tempfile.mkstemp(dir=directorio(), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"key": llave, "expires": expira.timestamp(), "data": datos}, f, default=str)
        os.replace(temporal, _ruta(llave))
    except OSError as exc:
        # Sin cache la vista sigue funcionando, solo que consulta la base.
        print(f"[readmodel] No se pudo guardar la cache: {exc}")


def invalidar(prefijo: str) -> int:
    """Borra las entradas cuyo nombre empieza por `prefijo` (p. ej. "findings")."""
    borradas = 0
    for ruta in directorio().glob("*.json"):
        try:
            if json.loads(ruta.read_text(encoding="utf-8")).get("key", "").startswith(prefijo + ":"):
                ruta.unlink()
                borradas += 1
        except (OSError, ValueError):
            continue
    return borradas

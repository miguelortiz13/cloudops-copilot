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

# Hora UTC del recolector diario (collector_cron) y margen para que termine.
# Una vista vale hasta que la *siguiente* recoleccion haya terminado.
HORA_RECOLECCION = int(os.getenv("COLLECTOR_HOUR_UTC", "6"))
MARGEN = timedelta(hours=1)


def directorio() -> Path:
    return Path(config.DATA_DIR) / "readmodel"


def proxima_renovacion(ahora: Optional[datetime] = None) -> datetime:
    """
    Cuando habra datos nuevos: la proxima recoleccion que todavia no empezo,
    mas el margen.

    Antes se calculaba como "las 07:00 siguientes": una vista escrita por el
    recolector a las 06:02 vencia a las 07:00, y desde ahi cada visita al
    panel despertaba la base.
    """
    ahora = ahora or datetime.now(timezone.utc)
    corrida = ahora.replace(hour=HORA_RECOLECCION, minute=0, second=0, microsecond=0)
    if corrida <= ahora:
        corrida += timedelta(days=1)
    return corrida + MARGEN


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

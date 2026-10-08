"""Piezas comunes de los recolectores."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def ahora() -> datetime:
    return datetime.now(timezone.utc)


def account_uid(subscription_id: str) -> str:
    return f"azure:sub/{(subscription_id or '').lower()}"


def resource_uid(resource_id: str) -> str:
    """uid universal de un recurso de Azure: prefijo de proveedor e id en minusculas."""
    return f"azure:{(resource_id or '').lower()}"


@dataclass
class Resultado:
    """Lo que devuelve un recolector: se guarda en collector_runs."""

    items: int = 0
    # ok | parcial: parcial cuando parte del alcance no respondio (permisos,
    # limite de tasa) y lo recolectado sigue siendo valido.
    status: str = "ok"
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Contexto:
    """Servicios y alcance compartidos por los recolectores de una ejecucion."""

    azure: Any
    inventory: Any
    cost: Any
    secops: Any
    subscription_ids: List[str] = field(default_factory=list)
    subscription_names: Dict[str, str] = field(default_factory=dict)
    # Fecha de la ejecucion; las pruebas la fijan.
    momento: Optional[datetime] = None

    def __post_init__(self):
        if self.momento is None:
            self.momento = ahora()

"""Piezas comunes de los recolectores."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def ahora() -> datetime:
    return datetime.now(timezone.utc)


# Identificadores de Azure, para los pasos que todavía son propios de Azure
# (KPIs de gobernanza, caché de costos en vivo). Los recolectores del modelo
# canónico usan los uids que entrega el proveedor.
from app.providers.azure.provider import account_uid, resource_uid  # noqa: E402,F401
from app.providers.base import Cuenta  # noqa: E402


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
    """
    Proveedor, alcance y servicios compartidos por los recolectores de una ejecucion.

    Inventario, costos y hallazgos solo hablan con `proveedor` (app/providers):
    no saben de que nube vienen los datos. `inventory` y `cost` quedan para los
    pasos que aun son propios de Azure (KPIs de gobernanza y cache de costos del
    panel en vivo).
    """

    azure: Any
    inventory: Any
    cost: Any
    secops: Any
    subscription_ids: List[str] = field(default_factory=list)
    subscription_names: Dict[str, str] = field(default_factory=dict)
    # Fecha de la ejecucion; las pruebas la fijan.
    momento: Optional[datetime] = None
    proveedor: Any = None
    # Cuentas del alcance, en el modelo canonico. Si no se dan, salen de las
    # suscripciones (Azure).
    cuentas: List[Cuenta] = field(default_factory=list)

    def __post_init__(self):
        if self.momento is None:
            self.momento = ahora()
        if not self.cuentas and self.subscription_ids:
            self.cuentas = [Cuenta(uid=account_uid(s), provider="azure", native_id=s,
                                   name=self.subscription_names.get(s) or s) for s in self.subscription_ids]

    @property
    def cuentas_uid(self) -> List[str]:
        return [c.uid for c in self.cuentas]

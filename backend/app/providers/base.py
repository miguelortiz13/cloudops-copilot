"""
Contrato de la capa de proveedores (ADR 0006).

Cada nube implementa estas interfaces y devuelve solo el modelo canónico. El
resto del sistema (recolectores, API, panel) no conoce KQL, ARN ni SDK.

Reglas del contrato, verificadas por tests/contract/ contra cada proveedor:

* **Modelo canónico.** Cuentas y recursos con `uid` universal y el prefijo de
  su proveedor (`azure:...`, `aws:...`); tipos canónicos o None, nunca
  inventados; costos en FOCUS con fecha, moneda ISO y montos Decimal.
* **Un fallo no es un vacío.** Si una consulta no respondió, se lanza
  `ProveedorError` (inventario) o se informa en la cobertura (costos por
  cuenta, reglas sin evidencia en seguridad). Nunca se devuelve una lista
  vacía que el recolector leería como "ya no hay nada".
* **Capacidades declaradas.** Lo que el proveedor no soporta (o no está
  configurado) lanza `CapacidadNoSoportada`: el panel lo muestra como "no
  disponible", nunca como cero.
* **Cuentas canónicas en la entrada.** Los métodos reciben uids de cuenta
  (`azure:sub/<id>`), no ids nativos.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Protocol, Sequence, runtime_checkable


class Capacidad(str, Enum):
    INVENTARIO = "inventario"
    COSTOS = "costos"
    SEGURIDAD = "seguridad"
    IAC = "iac"
    ACTIVIDAD = "actividad"


class ProveedorError(RuntimeError):
    """La nube no respondió (o respondió a medias): no hay datos en los que confiar."""


class CapacidadNoSoportada(RuntimeError):
    """El proveedor no implementa, o no tiene configurada, esta capacidad."""


# ---------------------------------------------------------------- modelo canónico

# Vocabulario de tipos canónicos: el mismo para todas las nubes. Un proveedor
# mapea sus tipos nativos a uno de estos o a None (se guarda con su tipo
# nativo); nunca inventa uno. Agregar una nube puede ampliar la lista.
TIPOS_CANONICOS: FrozenSet[str] = frozenset({
    "compute.vm", "compute.vm_scale_set", "compute.app", "compute.app_plan", "compute.container_app",
    "compute.container_platform", "compute.job", "kubernetes.cluster", "container.registry",
    "storage.account", "storage.bucket", "storage.disk", "storage.snapshot",
    "network.vnet", "network.interface", "network.public_ip", "network.firewall_rules", "network.load_balancer",
    "database.server", "database.sql", "database.nosql", "secrets.vault", "identity.managed",
    "web.static_site", "observability.apm", "observability.logs",
})


@dataclass(frozen=True)
class Cuenta:
    uid: str
    provider: str
    native_id: str
    name: str
    # Grupo de administración u OU, si se conoce.
    parent: Optional[str] = None


@dataclass(frozen=True)
class Recurso:
    uid: str
    provider: str
    account_uid: str
    native_id: str
    name: str
    native_type: str
    canonical_type: Optional[str]
    region: Optional[str]
    group_name: Optional[str]
    tags: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CostoDiario:
    """Una fila FOCUS: gasto de un día, recurso y servicio."""

    charge_date: date
    account_uid: str
    # Vacío para cargos sin recurso (soporte, marketplace, impuestos).
    resource_uid: str
    service_name: str
    billed_cost: Decimal
    effective_cost: Decimal
    currency: str


@dataclass
class Cobertura:
    """Qué cuentas respondieron. Una cuenta fuera de `cubiertas` no tiene dato, no tiene cero."""

    cubiertas: List[str] = field(default_factory=list)
    denegadas: List[str] = field(default_factory=list)
    fallidas: List[str] = field(default_factory=list)
    # Cuentas que fallaron y respondieron al reintentar.
    recuperadas: int = 0


@dataclass
class ResultadoCostos:
    filas: List[CostoDiario]
    cobertura: Cobertura


@dataclass(frozen=True)
class Hallazgo:
    """Una regla del catálogo (app/compliance/catalog.py) que falla en un recurso."""

    rule_id: str
    # Puede ser más fino que un recurso del inventario (una regla de un NSG).
    resource_uid: str
    account_uid: str
    severity: str
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class ResultadoSeguridad:
    hallazgos: List[Hallazgo]
    # Reglas que no se pudieron evaluar: sus hallazgos previos no se dan por resueltos.
    reglas_sin_evidencia: FrozenSet[str] = frozenset()


@dataclass(frozen=True)
class Creacion:
    resource_uid: str
    actor: str
    at: Optional[datetime]
    # Una persona (no un service principal ni una automatización).
    por_persona: bool


@dataclass
class ResultadoActividad:
    creaciones: List[Creacion]
    # Ventana observada: la nube conserva los eventos un tiempo limitado.
    desde: Optional[datetime] = None
    hasta: Optional[datetime] = None


# ---------------------------------------------------------------- interfaces por capacidad

@runtime_checkable
class Proveedor(Protocol):
    nombre: str

    def capacidades(self) -> FrozenSet[Capacidad]: ...


@runtime_checkable
class InventoryProvider(Protocol):
    def cuentas(self) -> List[Cuenta]:
        """Cuentas visibles para la identidad de la plataforma."""

    def recursos(self, cuentas: Sequence[str]) -> List[Recurso]:
        """Todos los recursos de esas cuentas. Lanza ProveedorError si la respuesta no está completa."""


@runtime_checkable
class CostProvider(Protocol):
    def costos_diarios(self, cuentas: Sequence[str], dias: int) -> ResultadoCostos:
        """Gasto diario por recurso y servicio de los últimos `dias`, con la cobertura por cuenta."""


@runtime_checkable
class SecurityProvider(Protocol):
    def evaluar_reglas(self, cuentas: Sequence[str]) -> ResultadoSeguridad:
        """Evalúa el catálogo de reglas sobre esas cuentas."""


@runtime_checkable
class IacStateProvider(Protocol):
    def recursos_gestionados(self) -> FrozenSet[str]:
        """uids de recursos que aparecen en algún estado de Terraform."""


@runtime_checkable
class ActivityProvider(Protocol):
    def creaciones(self, cuentas: Sequence[str]) -> ResultadoActividad:
        """Quién creó cada recurso, en la ventana que conserve la nube."""


def requiere(proveedor: Proveedor, capacidad: Capacidad) -> None:
    if capacidad not in proveedor.capacidades():
        raise CapacidadNoSoportada(f"{proveedor.nombre} no soporta {capacidad.value}.")


def resumen_capacidades(proveedor: Proveedor) -> Dict[str, bool]:
    """Para el panel: qué puede mostrar de cada proveedor."""
    tiene = proveedor.capacidades()
    return {c.value: c in tiene for c in Capacidad}

"""
Proveedor en memoria: cumple el contrato de app/providers/base.py con datos
fijos.

Es el doble de las pruebas de los recolectores. Pasa por la misma batería de
contrato que AzureProvider (tests/contract/), así que lo que los recolectores
aprenden de él vale para cualquier nube: si un proveedor real se comporta
distinto, falla su contrato, no una prueba de recolector.
"""

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Sequence, Set

from app.providers.base import (
    Capacidad, Cobertura, CostoDiario, Cuenta, Hallazgo, ProveedorError, Recurso,
    ResultadoActividad, ResultadoCostos, ResultadoSeguridad, requiere,
)


@dataclass
class ProveedorEnMemoria:
    nombre: str = "memoria"
    lista_cuentas: List[Cuenta] = field(default_factory=list)
    lista_recursos: List[Recurso] = field(default_factory=list)
    filas_costo: List[CostoDiario] = field(default_factory=list)
    hallazgos: List[Hallazgo] = field(default_factory=list)
    gestionados: Optional[Set[str]] = None
    actividad: Optional[ResultadoActividad] = None
    soporta: FrozenSet[Capacidad] = frozenset(Capacidad)

    # Fallas simuladas.
    inventario_roto: bool = False
    cuentas_fallidas_costos: Set[str] = field(default_factory=set)
    cuentas_denegadas_costos: Set[str] = field(default_factory=set)
    reglas_sin_evidencia: Set[str] = field(default_factory=set)

    # Lo que se pidió, para las aserciones.
    pedidos: Dict[str, list] = field(default_factory=dict)

    def _anotar(self, metodo: str, valor) -> None:
        self.pedidos.setdefault(metodo, []).append(valor)

    def capacidades(self) -> FrozenSet[Capacidad]:
        return frozenset(self.soporta)

    def _propias(self, cuentas: Sequence[str]) -> List[str]:
        prefijo = f"{self.nombre}:"
        ajenas = [c for c in cuentas if not c.startswith(prefijo)]
        if ajenas:
            raise ValueError(f"Cuentas de otro proveedor: {ajenas}")
        return list(cuentas)

    def cuentas(self) -> List[Cuenta]:
        requiere(self, Capacidad.INVENTARIO)
        return list(self.lista_cuentas)

    def recursos(self, cuentas: Sequence[str]) -> List[Recurso]:
        requiere(self, Capacidad.INVENTARIO)
        cuentas = self._propias(cuentas)
        self._anotar("recursos", list(cuentas))
        if self.inventario_roto:
            raise ProveedorError("Inventario incompleto: la consulta no respondió.")
        return [r for r in self.lista_recursos if r.account_uid in cuentas]

    def costos_diarios(self, cuentas: Sequence[str], dias: int) -> ResultadoCostos:
        requiere(self, Capacidad.COSTOS)
        cuentas = self._propias(cuentas)
        self._anotar("costos_diarios", dias)
        fuera = self.cuentas_fallidas_costos | self.cuentas_denegadas_costos
        cubiertas = [c for c in cuentas if c not in fuera]
        return ResultadoCostos(
            [f for f in self.filas_costo if f.account_uid in cubiertas],
            Cobertura(cubiertas=cubiertas, denegadas=[c for c in cuentas if c in self.cuentas_denegadas_costos],
                      fallidas=[c for c in cuentas if c in self.cuentas_fallidas_costos]),
        )

    def evaluar_reglas(self, cuentas: Sequence[str]) -> ResultadoSeguridad:
        requiere(self, Capacidad.SEGURIDAD)
        cuentas = self._propias(cuentas)
        return ResultadoSeguridad([h for h in self.hallazgos if h.account_uid in cuentas and h.rule_id not in self.reglas_sin_evidencia],
                                  frozenset(self.reglas_sin_evidencia))

    def recursos_gestionados(self) -> FrozenSet[str]:
        requiere(self, Capacidad.IAC)
        if self.gestionados is None:
            raise ProveedorError("Estados de Terraform no disponibles.")
        return frozenset(self.gestionados)

    def creaciones(self, cuentas: Sequence[str]) -> ResultadoActividad:
        requiere(self, Capacidad.ACTIVIDAD)
        self._propias(cuentas)
        if self.actividad is None:
            raise ProveedorError("Historial de actividad no disponible.")
        return self.actividad


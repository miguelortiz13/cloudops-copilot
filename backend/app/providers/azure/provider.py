"""
AzureProvider: el contrato de app/providers/base.py sobre Azure.

Envuelve los servicios existentes (Resource Graph, Cost Management, estados de
Terraform) sin cambiar su comportamiento y los traduce al modelo canónico. Aquí
vive lo que es propio de Azure y antes estaba en los recolectores:

* El uid de un hallazgo de NSG es la regla de seguridad, no el NSG: un mismo
  NSG puede tener varias reglas abiertas.
* Qué consulta KQL alimenta cada regla del catálogo, para saber qué reglas
  quedaron sin evidencia cuando una consulta falla.
* El reintento ante el 429 de Cost Management.
"""

import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

from app.compliance.catalog import CONSULTA_DE_TIPO, REGLAS
from app.providers.azure.types import canonical_type
from app.providers.base import (
    Capacidad, CapacidadNoSoportada, Cobertura, CostoDiario, Creacion, Cuenta, Hallazgo, ProveedorError, Recurso,
    ResultadoActividad, ResultadoCostos, ResultadoSeguridad,
)

PROVEEDOR = "azure"
PREFIJO_CUENTA = "azure:sub/"

# Cost Management corta con 429 cuando se agota la cuota de la ventana. Las
# suscripciones que fallaron se reintentan una vez, más despacio, tras esperar
# a que se libere (la misma estrategia que la precarga de costos).
ESPERA_REINTENTO_SEGUNDOS = 60
PAUSA_COSTOS = 2.0

# Lo que se guarda de cada hallazgo: datos para entender el problema, sin la
# estructura nativa completa.
CAMPOS_DETALLE = ("name", "resourceGroup", "location", "port", "source", "ruleName", "asociado", "sinFirewall", "type")


def account_uid(subscription_id: str) -> str:
    return f"{PREFIJO_CUENTA}{(subscription_id or '').lower()}"


def resource_uid(resource_id: str) -> str:
    """uid universal de un recurso de Azure: prefijo de proveedor e id en minúsculas."""
    return f"azure:{(resource_id or '').lower()}"


def suscripcion_de(cuenta_uid: str) -> str:
    if not cuenta_uid.startswith(PREFIJO_CUENTA):
        raise ValueError(f"No es una cuenta de Azure: {cuenta_uid}")
    return cuenta_uid[len(PREFIJO_CUENTA):]


def _uid_del_hallazgo(tipo: str, item: Dict[str, Any]) -> str:
    if tipo == "nsg" and item.get("ruleName"):
        return resource_uid(f"{item['id']}/securityRules/{item['ruleName']}")
    return resource_uid(item.get("id", ""))


def _fecha(valor: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00")) if valor else None
    except ValueError:
        return None


class AzureProvider:
    nombre = PROVEEDOR

    def __init__(self, inventory, cost, secops, tfstate=None, espera_reintento: Optional[float] = None):
        self._inventory = inventory
        self._cost = cost
        self._secops = secops
        self._tfstate = tfstate
        self._espera = ESPERA_REINTENTO_SEGUNDOS if espera_reintento is None else espera_reintento

    @classmethod
    def desde_cliente(cls, azure, **kw) -> "AzureProvider":
        """Arma los servicios sobre un AzureClient ya autenticado."""
        from app.services import tfstate_service
        from app.services.cost_service import CostService
        from app.services.inventory_service import InventoryService
        from app.services.secops_service import SecOpsService

        inventario = InventoryService(azure)
        tfstate = tfstate_service.TfStateService(azure) if tfstate_service.ENABLED else None
        if tfstate is not None:
            inventario.attach_tfstate(tfstate)
        return cls(inventario, CostService(azure), SecOpsService(azure), tfstate, **kw)

    def capacidades(self) -> FrozenSet[Capacidad]:
        base = {Capacidad.INVENTARIO, Capacidad.COSTOS, Capacidad.SEGURIDAD, Capacidad.ACTIVIDAD}
        if self._tfstate is not None:
            base.add(Capacidad.IAC)
        return frozenset(base)

    # ------------------------------------------------------------ inventario

    def cuentas(self) -> List[Cuenta]:
        subs, avisos = self._inventory.list_accessible_subscriptions()
        if not subs and avisos:
            raise ProveedorError("; ".join(avisos))
        return [Cuenta(uid=account_uid(s["subscriptionId"]), provider=PROVEEDOR, native_id=s["subscriptionId"],
                       name=s.get("displayName") or s["subscriptionId"])
                for s in subs if s.get("subscriptionId")]

    def recursos(self, cuentas: Sequence[str]) -> List[Recurso]:
        subs = [suscripcion_de(c) for c in cuentas]
        if not subs:
            return []
        items, avisos = self._inventory._fetch_all_resources(subs, force_refresh=True, strict=True)
        if avisos:
            # En modo estricto, cualquier aviso es una consulta que no respondió entera.
            raise ProveedorError("Inventario incompleto: " + "; ".join(avisos))
        vistos: Dict[str, Recurso] = {}
        for item in items:
            if not item.get("id"):
                continue
            uid = resource_uid(item["id"])
            if uid in vistos:
                continue
            tipo = (item.get("type") or "").lower()
            vistos[uid] = Recurso(
                uid=uid, provider=PROVEEDOR, account_uid=account_uid(item.get("subscriptionId", "")),
                native_id=item["id"], name=item.get("name") or "", native_type=tipo, canonical_type=canonical_type(tipo),
                region=item.get("location") or None, group_name=item.get("resourceGroup") or None,
                tags={str(k): str(v) for k, v in (item.get("tags") or {}).items() if v is not None},
            )
        return list(vistos.values())

    # ------------------------------------------------------------ costos

    def _consultar_costos(self, subs: List[str], dias: int) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]], int]:
        datos = self._cost.get_daily_cost_by_resource(subs, days=dias, pace_seconds=PAUSA_COSTOS)
        cobertura = {k: list(v) for k, v in (datos.get("coverage") or {}).items()}
        filas = list(datos.get("rows") or [])
        fallidas = cobertura.get("failed") or []
        if not fallidas:
            return filas, cobertura, 0
        print(f"[azure] costos: reintentando {len(fallidas)} suscripcion(es) en {self._espera:.0f} s.")
        time.sleep(self._espera)
        segunda = self._cost.get_daily_cost_by_resource(fallidas, days=dias, pace_seconds=PAUSA_COSTOS * 2)
        recuperadas = (segunda.get("coverage") or {}).get("covered") or []
        filas += [f for f in segunda.get("rows") or [] if f.get("subscription_id") in recuperadas]
        cobertura["covered"] = (cobertura.get("covered") or []) + recuperadas
        cobertura["failed"] = [s for s in fallidas if s not in recuperadas]
        cobertura["denied"] = (cobertura.get("denied") or []) + ((segunda.get("coverage") or {}).get("denied") or [])
        return filas, cobertura, len(recuperadas)

    def costos_diarios(self, cuentas: Sequence[str], dias: int) -> ResultadoCostos:
        subs = [suscripcion_de(c) for c in cuentas]
        if not subs:
            return ResultadoCostos([], Cobertura())
        crudas, cobertura, recuperadas = self._consultar_costos(subs, dias)
        cubiertas = {s.lower() for s in cobertura.get("covered") or []}

        # Una fila por (día, cuenta, recurso, servicio): Cost Management puede
        # repetir combinaciones (el mismo recurso con distinta capitalización).
        sumas: Dict[Tuple[date, str, str, str], Tuple[Decimal, str]] = {}
        for f in crudas:
            # Solo cuentas cubiertas: de las demás no hay dato completo.
            if str(f.get("subscription_id", "")).lower() not in cubiertas:
                continue
            clave = (date.fromisoformat(f["date"]), account_uid(f["subscription_id"]),
                     resource_uid(f["resource_id"]) if f.get("resource_id") else "", (f.get("service_name") or "")[:200])
            monto = Decimal(str(round(float(f.get("cost") or 0), 6)))
            previo = sumas.get(clave)
            sumas[clave] = (previo[0] + monto, previo[1]) if previo else (monto, (f.get("currency") or "USD")[:3].upper())

        filas = [CostoDiario(charge_date=d, account_uid=c, resource_uid=r, service_name=s, billed_cost=m,
                             effective_cost=m, currency=moneda)
                 for (d, c, r, s), (m, moneda) in sumas.items()]
        return ResultadoCostos(filas, Cobertura(
            cubiertas=[account_uid(s) for s in cobertura.get("covered") or []],
            denegadas=[account_uid(s) for s in cobertura.get("denied") or []],
            fallidas=[account_uid(s) for s in cobertura.get("failed") or []],
            recuperadas=recuperadas,
        ))

    # ------------------------------------------------------------ seguridad

    def evaluar_reglas(self, cuentas: Sequence[str]) -> ResultadoSeguridad:
        subs = [suscripcion_de(c) for c in cuentas]
        reporte = self._secops.build_report(subs, strict=True)
        fallidas = set(reporte.get("failed_queries") or [])
        sin_evidencia = frozenset(REGLAS[t].id for t, consulta in CONSULTA_DE_TIPO.items() if consulta in fallidas)

        hallazgos: Dict[Tuple[str, str], Hallazgo] = {}
        for item in reporte.get("findings") or []:
            regla = REGLAS.get(item.get("tipo"))
            if regla is None or not item.get("id"):
                continue
            h = Hallazgo(
                rule_id=regla.id, resource_uid=_uid_del_hallazgo(item["tipo"], item),
                account_uid=account_uid(item.get("subscriptionId", "")), severity=item.get("severidad") or regla.severity_default,
                details={k: item[k] for k in CAMPOS_DETALLE if item.get(k) is not None},
            )
            hallazgos[(h.rule_id, h.resource_uid)] = h
        return ResultadoSeguridad(list(hallazgos.values()), sin_evidencia)

    # ------------------------------------------------------------ IaC y actividad

    def recursos_gestionados(self) -> FrozenSet[str]:
        if self._tfstate is None:
            raise CapacidadNoSoportada("No hay cuentas de estado de Terraform configuradas (TFSTATE_ACCOUNT).")
        try:
            datos = self._tfstate.get_index()
        except Exception as exc:
            raise ProveedorError(f"No se pudieron leer los estados de Terraform: {exc}") from exc
        if not datos.get("available"):
            raise ProveedorError(f"Estados de Terraform no disponibles: {datos.get('reason') or 'sin estados legibles'}.")
        return frozenset(resource_uid(str(i)) for i in datos.get("managed_ids") or ())

    def creaciones(self, cuentas: Sequence[str]) -> ResultadoActividad:
        subs = [suscripcion_de(c) for c in cuentas]
        try:
            datos = self._inventory.get_manual_creations(subs, limit=100_000)
        except Exception as exc:
            raise ProveedorError(f"No se pudo leer el historial de cambios: {exc}") from exc
        if not datos.get("available"):
            # get_manual_creations no distingue "sin eventos" de "falló": ninguno es un dato.
            raise ProveedorError("El historial de cambios de Resource Graph no respondió o no tiene eventos.")
        return ResultadoActividad(
            creaciones=[Creacion(resource_uid=resource_uid(m["id"]), actor=m["createdBy"], at=_fecha(m.get("createdAt")),
                                 por_persona=True)
                        for m in datos.get("manualCreations") or [] if m.get("id") and m.get("createdBy")],
            desde=_fecha(datos.get("windowFrom")), hasta=_fecha(datos.get("windowTo")),
        )

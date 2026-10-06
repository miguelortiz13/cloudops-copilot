"""
Vista global de costos: cuanto se gasta, en que y donde, antes de hablar de ahorro.

El reporte de FinOps empezaba por el desperdicio —discos huerfanos, IPs libres—
sin haber mostrado nunca cuanto cuesta la nube ni en que se va el dinero. Para
decidir que optimizar primero hay que ver el gasto completo: un disco huerfano de
3 USD no importa en una cuenta de 10.000, y si en una de 30.

Este servicio no lanza consultas nuevas por recurso. Reutiliza los dos datos que
`CostService` ya mantiene en cache (y que precarga en segundo plano):

* el gasto por recurso de los ultimos 30 dias, del que salen todos los desgloses
  (suscripcion, grupo, servicio, region, tags) y el ranking de recursos;
* la serie diaria, de la que salen los totales, la comparacion con el periodo
  anterior, el mes en curso y la proyeccion de cierre.

Las dos fuentes no suman exactamente lo mismo: la serie diaria incluye cargos que
no pertenecen a ningun recurso (soporte, Marketplace, reservas). Esa diferencia
se publica aparte, como "cargos sin recurso", en vez de esconderla.

Todas las cifras son facturacion real de Cost Management. Las suscripciones sin
cobertura se declaran en `coverage` y no se rellenan con estimaciones: esta vista
responde "cuanto se pago", y una estimacion no es eso.
"""

import calendar
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core import config
from app.services import cost_service as cost_module

# Ventana de la serie diaria: dos periodos de 30 dias para poder comparar.
DAILY_WINDOW_DAYS = 60
PERIOD_DAYS = 30
TOP_RESOURCES = 25
TOP_GROUPS = 12

# Nombres legibles de los servicios mas comunes. El resto se deriva del tipo.
SERVICE_NAMES: Dict[str, str] = {
    "microsoft.web/sites": "App Service y Functions",
    "microsoft.web/serverfarms": "Planes de App Service",
    "microsoft.web/staticsites": "Static Web Apps",
    "microsoft.app/containerapps": "Container Apps",
    "microsoft.app/managedenvironments": "Container Apps (entornos)",
    "microsoft.containerregistry/registries": "Container Registry",
    "microsoft.containerservice/managedclusters": "Kubernetes Service (AKS)",
    "microsoft.compute/virtualmachines": "Máquinas virtuales",
    "microsoft.compute/virtualmachinescalesets": "Conjuntos de escalado",
    "microsoft.compute/disks": "Discos administrados",
    "microsoft.compute/snapshots": "Snapshots",
    "microsoft.storage/storageaccounts": "Storage",
    "microsoft.keyvault/vaults": "Key Vault",
    "microsoft.operationalinsights/workspaces": "Log Analytics",
    "microsoft.insights/components": "Application Insights",
    "microsoft.cognitiveservices/accounts": "Azure AI Services",
    "microsoft.sql/servers": "SQL Database",
    "microsoft.sql/servers/databases": "SQL Database",
    "microsoft.dbforpostgresql/flexibleservers": "PostgreSQL",
    "microsoft.dbformysql/flexibleservers": "MySQL",
    "microsoft.documentdb/databaseaccounts": "Cosmos DB",
    "microsoft.cache/redis": "Cache for Redis",
    "microsoft.network/publicipaddresses": "IPs públicas",
    "microsoft.network/loadbalancers": "Load Balancer",
    "microsoft.network/applicationgateways": "Application Gateway",
    "microsoft.network/virtualnetworkgateways": "VPN Gateway",
    "microsoft.network/natgateways": "NAT Gateway",
    "microsoft.network/azurefirewalls": "Azure Firewall",
    "microsoft.network/frontdoors": "Front Door",
    "microsoft.cdn/profiles": "Front Door y CDN",
    "microsoft.network/privateendpoints": "Private Link",
    "microsoft.network/dnszones": "DNS",
    "microsoft.network/privatednszones": "DNS privado",
    "microsoft.network/bastionhosts": "Bastion",
    "microsoft.eventhub/namespaces": "Event Hubs",
    "microsoft.servicebus/namespaces": "Service Bus",
    "microsoft.logic/workflows": "Logic Apps",
    "microsoft.apimanagement/service": "API Management",
    "microsoft.datafactory/factories": "Data Factory",
    "microsoft.databricks/workspaces": "Databricks",
    "microsoft.recoveryservices/vaults": "Backup y Site Recovery",
    "microsoft.botservice/botservices": "Bot Service",
}


def tipo_de(resource_id: str) -> str:
    """
    Tipo ARM de un resource id: `microsoft.storage/storageaccounts`.

    Para subrecursos (`.../servers/x/databases/y`) devuelve el tipo completo
    (`microsoft.sql/servers/databases`).
    """
    partes = str(resource_id or "").lower().strip("/").split("/")
    if "providers" not in partes:
        return ""
    i = partes.index("providers")
    resto = partes[i + 1:]
    if len(resto) < 3:
        return ""
    proveedor, segmentos = resto[0], resto[1:]
    tipos = segmentos[0::2]
    return f"{proveedor}/{'/'.join(tipos)}"


def servicio_de(tipo: str) -> str:
    """Nombre legible del servicio a partir del tipo ARM."""
    tipo = (tipo or "").lower()
    if tipo in SERVICE_NAMES:
        return SERVICE_NAMES[tipo]
    raiz = "/".join(tipo.split("/")[:2])
    if raiz in SERVICE_NAMES:
        return SERVICE_NAMES[raiz]
    ultimo = tipo.split("/")[-1] if tipo else ""
    return ultimo or "Otros"


def _partes_id(resource_id: str) -> Tuple[str, str]:
    """(grupo de recursos, nombre) a partir del id."""
    partes = str(resource_id or "").strip("/").split("/")
    grupo = ""
    lower = [p.lower() for p in partes]
    if "resourcegroups" in lower:
        i = lower.index("resourcegroups")
        if i + 1 < len(partes):
            grupo = partes[i + 1]
    nombre = partes[-1] if partes else ""
    return grupo, nombre


def _redondear(valor: float) -> float:
    return round(float(valor or 0.0), 2)


def _agrupar(
    filas: Iterable[Tuple[str, float]], total: float, limite: Optional[int] = TOP_GROUPS
) -> List[Dict[str, Any]]:
    """
    Suma por clave y devuelve `[{key, cost, share}]` de mayor a menor.

    Si hay mas claves que `limite`, el resto se agrupa en "Otros" para que el
    desglose siempre sume el total.
    """
    acumulado: Dict[str, float] = {}
    for clave, monto in filas:
        acumulado[clave] = acumulado.get(clave, 0.0) + monto
    ordenado = sorted(acumulado.items(), key=lambda kv: kv[1], reverse=True)
    if limite and len(ordenado) > limite:
        resto = sum(m for _, m in ordenado[limite - 1:])
        ordenado = ordenado[: limite - 1] + [("Otros", resto)]
    return [
        {
            "key": clave,
            "cost": _redondear(monto),
            "share": round(monto / total * 100, 1) if total else 0.0,
        }
        for clave, monto in ordenado
        if abs(monto) >= 0.005
    ]


def resumir_serie(serie: Dict[str, float], hoy: date) -> Dict[str, Any]:
    """
    Totales a partir de la serie diaria.

    - `last_period`: ultimos 30 dias de la ventana; `previous_period`: los 30
      anteriores. La ventana termina ayer porque Cost Management consolida con
      retraso: el dia en curso siempre estaria incompleto.
    - `month_to_date`: lo facturado desde el dia 1 del mes en curso.
    - `forecast_month`: proyeccion lineal del cierre de mes con el promedio de
      los ultimos 7 dias. Es una proyeccion, y la respuesta lo declara.
    """
    fin = hoy - timedelta(days=1)
    dias = [fin - timedelta(days=i) for i in range(DAILY_WINDOW_DAYS)][::-1]
    valores = {d: float(serie.get(d.isoformat(), 0.0)) for d in dias}

    ultimos = [valores[d] for d in dias[-PERIOD_DAYS:]]
    previos = [valores[d] for d in dias[:-PERIOD_DAYS]]
    last_period = sum(ultimos)
    previous_period = sum(previos)

    inicio_mes = hoy.replace(day=1)
    mtd = sum(v for d, v in valores.items() if d >= inicio_mes)
    dias_mes = calendar.monthrange(hoy.year, hoy.month)[1]
    restantes = dias_mes - (hoy.day - 1)
    promedio_7 = sum(ultimos[-7:]) / 7 if ultimos else 0.0

    delta = None
    if previous_period > 0:
        delta = round((last_period - previous_period) / previous_period * 100, 1)

    return {
        "last_period": _redondear(last_period),
        "previous_period": _redondear(previous_period),
        "delta_percentage": delta,
        "daily_average": _redondear(last_period / PERIOD_DAYS),
        "month_to_date": _redondear(mtd),
        "forecast_month": _redondear(mtd + promedio_7 * restantes),
        "period_days": PERIOD_DAYS,
        "period_start": dias[-PERIOD_DAYS].isoformat(),
        "period_end": fin.isoformat(),
        "daily": [{"date": d.isoformat(), "cost": _redondear(valores[d])} for d in dias],
    }


class CostOverviewService:
    """Agrega el gasto real del scope en totales, desgloses y ranking."""

    def __init__(self, agent, cost_service):
        self.agent = agent
        self.cost = cost_service

    def _resolver_scope(self, subscription_ids: Optional[List[str]]) -> List[str]:
        if subscription_ids:
            return [s for s in subscription_ids if s]
        filas = self.agent.query_azure_resource_graph(
            "resourcecontainers | where type == 'microsoft.resources/subscriptions' "
            "| project subscriptionId",
            False,
            [],
        ) or []
        return [f["subscriptionId"] for f in filas if f.get("subscriptionId")]

    def build(self, subscription_ids: Optional[List[str]] = None, hoy: Optional[date] = None) -> Dict[str, Any]:
        subs = self._resolver_scope(subscription_ids)
        hoy = hoy or datetime.now(timezone.utc).date()

        with ThreadPoolExecutor(max_workers=4) as executor:
            f_por_recurso = executor.submit(self.cost.costs_for, subs)
            f_diario = executor.submit(self.cost.get_daily_costs, subs, DAILY_WINDOW_DAYS)
            f_recursos = executor.submit(
                self.agent.query_azure_resource_graph,
                "resources | project id, name, type, resourceGroup, location, subscriptionId, tags",
                False,
                subs,
            )
            f_subs = executor.submit(
                self.agent.query_azure_resource_graph,
                "resourcecontainers | where type == 'microsoft.resources/subscriptions' "
                "| project subscriptionId, name",
                False,
                subs,
            )
            por_recurso = f_por_recurso.result() or {}
            diario = f_diario.result() or {}
            recursos = f_recursos.result() or []
            nombres_subs = {
                str(f.get("subscriptionId") or "").lower(): f.get("name")
                for f in (f_subs.result() or [])
            }

        coverage = por_recurso.get("coverage") or {"covered": [], "denied": [], "failed": []}
        costos: Dict[str, float] = por_recurso.get("costs") or {}
        moneda = por_recurso.get("currency") or diario.get("currency") or "USD"
        ventana = por_recurso.get("window_days") or PERIOD_DAYS

        inventario = {str(r.get("id") or "").lower(): r for r in recursos if r.get("id")}

        # --- Recursos con costo, enriquecidos con el inventario ---------------
        filas: List[Dict[str, Any]] = []
        for rid, monto in costos.items():
            if abs(monto) < 0.005:
                continue
            inv = inventario.get(rid)
            tipo = str((inv or {}).get("type") or tipo_de(rid)).lower()
            grupo, nombre = _partes_id(rid)
            sub = cost_module.subscription_of(rid)
            tags = (inv or {}).get("tags") or {}
            tags_lower = {str(k).lower(): v for k, v in tags.items()}
            filas.append({
                "id": rid,
                "name": (inv or {}).get("name") or nombre,
                "type": tipo,
                "service": servicio_de(tipo),
                "resourceGroup": (inv or {}).get("resourceGroup") or grupo.lower(),
                "subscriptionId": sub,
                "subscriptionName": nombres_subs.get(sub) or sub,
                "location": (inv or {}).get("location") or "",
                # Un recurso facturado en la ventana que ya no esta en Azure:
                # su costo es real, y conviene saber que se borro.
                "deleted": inv is None,
                "tags": {t: tags_lower.get(t.lower()) for t in config.SHOWBACK_TAGS},
                "cost": monto,
            })

        total_recursos = sum(f["cost"] for f in filas)

        # --- Totales desde la serie diaria ------------------------------------
        serie = diario.get("series") or {}
        if serie:
            resumen = resumir_serie(serie, hoy)
        else:
            # Sin serie diaria (fallo puntual) se usa el gasto por recurso: el
            # total sigue siendo real, pero no hay comparacion ni proyeccion.
            resumen = {
                "last_period": _redondear(total_recursos), "previous_period": None,
                "delta_percentage": None, "daily_average": _redondear(total_recursos / ventana),
                "month_to_date": None, "forecast_month": None, "period_days": ventana,
                "period_start": None, "period_end": None, "daily": [],
            }

        total = max(total_recursos, resumen["last_period"] or 0.0)
        sin_recurso = _redondear(max(0.0, (resumen["last_period"] or 0.0) - total_recursos))

        def por(campo: str):
            return ((f[campo] or "—", f["cost"]) for f in filas)

        por_tag = {}
        for tag in config.SHOWBACK_TAGS:
            por_tag[tag] = _agrupar(
                ((f["tags"].get(tag) or f"Sin {tag}", f["cost"]) for f in filas), total
            )

        ranking = sorted(filas, key=lambda f: f["cost"], reverse=True)[:TOP_RESOURCES]
        for f in ranking:
            f["share"] = round(f["cost"] / total * 100, 1) if total else 0.0
            f["cost"] = _redondear(f["cost"])

        n_cubiertas = len(coverage.get("covered", []))
        n_total = n_cubiertas + len(coverage.get("denied", [])) + len(coverage.get("failed", []))
        if n_cubiertas == 0:
            basis, mensaje = "unavailable", (
                "Sin facturación disponible para el scope: ninguna suscripción respondió "
                "a Cost Management."
            )
        elif n_cubiertas < n_total:
            basis, mensaje = "partial", (
                f"Facturación real de {n_cubiertas} de {n_total} suscripciones. Las demás "
                "no se incluyen en los totales."
            )
        else:
            basis, mensaje = "actual", f"Facturación real de Azure Cost Management ({n_total} suscripciones)."

        return {
            "basis": basis,
            "message": mensaje,
            "currency": moneda,
            "window_days": ventana,
            "coverage": {
                **coverage,
                "covered_names": [nombres_subs.get(s.lower()) or s for s in coverage.get("covered", [])],
                "uncovered_names": [
                    nombres_subs.get(s.lower()) or s
                    for s in list(coverage.get("denied", [])) + list(coverage.get("failed", []))
                ],
            },
            "cache_age_seconds": por_recurso.get("cache_age_seconds", 0),
            "totals": {
                **{k: v for k, v in resumen.items() if k != "daily"},
                "resource_attributed": _redondear(total_recursos),
                "unassigned_charges": sin_recurso,
                "resources_with_cost": len(filas),
                "deleted_resources_with_cost": sum(1 for f in filas if f["deleted"]),
            },
            "daily": resumen["daily"],
            "by_subscription": _agrupar(((f["subscriptionName"], f["cost"]) for f in filas), total),
            "by_resource_group": _agrupar(por("resourceGroup"), total),
            "by_service": _agrupar(por("service"), total),
            "by_location": _agrupar(por("location"), total),
            "by_tag": por_tag,
            "top_resources": ranking,
        }

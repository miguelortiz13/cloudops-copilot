"""
Consultas en vivo del agente que también usan los routers heredados y el bot:
KPIs del tenant, búsqueda de recursos y costo de un grupo de recursos.

Funciones de módulo que reciben el agente (como rule_answers), para usar su
cliente de Azure y el CostService compartido con el panel.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from app.core import config
from app.services import cost_service, governance, pricing


def resumen_en_vivo(agente, subscriptions: Optional[List[str]] = None) -> Dict[str, Any]:
    """Calculates current statistics of the Azure Subscription in real-time."""
    if not agente.azure.azure_connected:
        return {
            "total_resources": 0,
            "terraform_managed": 0,
            "portal_managed": 0,
            "unknown_managed": 0,
            "terraform_percentage": 0,
            "missing_owner_tags": 0,
            "missing_environment_tags": 0,
            "tag_compliance_percentage": 0,
            "top_subscriptions": {},
            "domain_distribution": {},
            "import_required": 0,
            "orphaned_disks": 0,
            "orphaned_ips": 0,
            "orphaned_nics": 0,
            "exposed_nsgs": 0,
            "failed_resources": 0,
            "estimated_monthly_savings": 0.0,
            "error": "Azure API desconectada. Revisa tus credenciales en el archivo .env"
        }

    try:
        # Execute all statistical queries in parallel
        with ThreadPoolExecutor(max_workers=9) as executor:
            # 1. Fetch tag compliance
            tags_obligatorias = config.MANDATORY_TAGS
            kql_stats = (
                "resources "
                + governance.kql_extends_tags_presentes(tags_obligatorias)
                + "| summarize total = count(), "
                + (governance.kql_conteo_faltantes(tags_obligatorias) + ", " if tags_obligatorias else "")
                + f"non_compliant = countif(not({governance.kql_todas_presentes(tags_obligatorias)}))"
            )
            f_stats = executor.submit(agente.azure.query_azure_resource_graph, kql_stats, False, subscriptions)

            # 2. Terraform-managed
            # La evidencia de IaC sale de services/governance.py, igual que
            # en el inventario. Antes esta consulta miraba solo tres claves
            # con el valor exacto 'terraform', asi que daba una cobertura
            # distinta a la del panel sobre el mismo tenant.
            f_tf = executor.submit(
                agente.azure.query_azure_resource_graph,
                "resources "
                "| extend _t = todynamic(tolower(tostring(tags))) "
                "| extend _json = tolower(tostring(tags)) "
                f"| where {governance.kql_tiene_iac()} "
                "| summarize count()",
                False,
                subscriptions
            )

            # 3. Resource type distribution
            f_types = executor.submit(
                agente.azure.query_azure_resource_graph,
                "resources | summarize count() by type | order by count_ desc | limit 6",
                False,
                subscriptions
            )

            # 4. Subscription distribution
            f_subs = executor.submit(
                agente.azure.query_azure_resource_graph,
                "resources | summarize count() by subscriptionId | limit 5",
                False,
                subscriptions
            )

            # 5. Unattached Disks
            f_disks = executor.submit(
                agente.azure.query_azure_resource_graph,
                "resources | where type =~ 'microsoft.compute/disks' and properties.diskState =~ 'Unattached' | summarize count()",
                False,
                subscriptions
            )

            # 6. Unassociated Public IPs
            f_ips = executor.submit(
                agente.azure.query_azure_resource_graph,
                "resources | where type =~ 'microsoft.network/publicipaddresses' and isnull(properties.ipConfiguration) | summarize count()",
                False,
                subscriptions
            )

            # 7. Orphaned Network Interfaces
            f_nics = executor.submit(
                agente.azure.query_azure_resource_graph,
                "resources | where type =~ 'microsoft.network/networkinterfaces' and isnull(properties.virtualMachine) | summarize count()",
                False,
                subscriptions
            )

            # 8. Exposed NSGs
            f_nsgs = executor.submit(
                agente.azure.query_azure_resource_graph,
                "resources | where type =~ 'microsoft.network/networksecuritygroups' | mv-expand rules=properties.securityRules | where rules.properties.direction =~ 'Inbound' and rules.properties.access =~ 'Allow' and (rules.properties.destinationPortRange in ('22', '3389', '*') or rules.properties.destinationPortRanges has '22' or rules.properties.destinationPortRanges has '3389') and (rules.properties.sourceAddressPrefix in ('*', '0.0.0.0/0', 'Internet') or rules.properties.sourceAddressPrefixes has '*' or rules.properties.sourceAddressPrefixes has 'Internet') | summarize count()",
                False,
                subscriptions
            )

            # 9. Failed resources
            f_failed = executor.submit(
                agente.azure.query_azure_resource_graph,
                "resources | where properties.provisioningState =~ 'Failed' | summarize count()",
                False,
                subscriptions
            )

            # Las nueve consultas comparten un limite total. Antes cada una
            # tenia su propio `timeout=8` y se resolvian en serie, de modo
            # que el peor caso eran 72 segundos y no 8; y como el `except`
            # era comun, la primera que expiraba vaciaba las nueve listas y
            # el panel aparecia sin datos aunque ocho hubieran respondido.
            pendientes = {
                "stats": f_stats, "tf": f_tf, "types": f_types, "subs": f_subs,
                "disks": f_disks, "ips": f_ips, "nics": f_nics,
                "nsgs": f_nsgs, "failed": f_failed,
            }
            cosecha = {}
            limite_kpis = time.monotonic() + agente.PRESUPUESTO_KPIS_SEGUNDOS
            for nombre, futuro in pendientes.items():
                try:
                    cosecha[nombre] = futuro.result(
                        timeout=max(0.1, limite_kpis - time.monotonic())
                    ) or []
                except Exception as ex:
                    print(f"KPI '{nombre}' sin resultado: {ex}")
                    cosecha[nombre] = []

            stats_raw = cosecha["stats"]
            res_tf, res_types, res_subs = cosecha["tf"], cosecha["types"], cosecha["subs"]
            res_disks, res_ips, res_nics = cosecha["disks"], cosecha["ips"], cosecha["nics"]
            res_nsgs, res_failed = cosecha["nsgs"], cosecha["failed"]

        if not stats_raw or stats_raw[0]['total'] == 0:
            total_resources = 0
            non_compliant = 0
            faltantes_por_tag = {t: 0 for t in config.MANDATORY_TAGS}
        else:
            row = stats_raw[0]
            total_resources = row['total']
            non_compliant = row['non_compliant']
            faltantes_por_tag = {
                t: int(row.get(governance.columna_faltantes(t)) or 0)
                for t in config.MANDATORY_TAGS
            }
        missing_env = next(
            (n for t, n in faltantes_por_tag.items() if t.lower() == "environment"), 0
        )

        tf_count = res_tf[0]['count_'] if res_tf else 0
        tf_percentage = (tf_count / total_resources * 100) if total_resources > 0 else 0
        tag_compliance = ((total_resources - non_compliant) / total_resources * 100) if total_resources > 0 else 0

        type_dist = {}
        for item in res_types:
            short_type = item['type'].split('/')[-1]
            type_dist[short_type] = item['count_']

        sub_dist = {item['subscriptionId']: item['count_'] for item in res_subs}
        orphaned_disks = res_disks[0]['count_'] if res_disks else 0
        orphaned_ips = res_ips[0]['count_'] if res_ips else 0
        orphaned_nics = res_nics[0]['count_'] if res_nics else 0
        exposed_nsgs = res_nsgs[0]['count_'] if res_nsgs else 0
        failed_resources = res_failed[0]['count_'] if res_failed else 0

        # Mismas tarifas que el resto de la plataforma: un panel y un chat
        # que discrepan en el ahorro estimado no son utilizables.
        estimated_savings = (orphaned_ips * pricing.IP_PUBLICA_MES) + (
            orphaned_disks * pricing.DISCO_HUERFANO_TIPICO_MES
        )

        return {
            "total_resources": int(total_resources),
            "terraform_managed": int(tf_count),
            "portal_managed": int(total_resources - tf_count),
            "unknown_managed": 0,
            "terraform_percentage": round(tf_percentage, 1),
            "missing_owner_tags": int(non_compliant), # Mapped to non-compliant for UI compatibility
            "missing_environment_tags": int(missing_env),
            "tag_compliance_percentage": round(tag_compliance, 1),
            "top_subscriptions": sub_dist,
            "domain_distribution": type_dist,
            "import_required": int(total_resources - tf_count),
            "missing_tags_detail": dict(faltantes_por_tag),
            "orphaned_disks": int(orphaned_disks),
            "orphaned_ips": int(orphaned_ips),
            "orphaned_nics": int(orphaned_nics),
            "exposed_nsgs": int(exposed_nsgs),
            "failed_resources": int(failed_resources),
            "estimated_monthly_savings": round(estimated_savings, 2)
        }
    except Exception as e:
        print(f"Error calculating live stats: {e}")
        return {"error": str(e)}


def nombre_de_suscripcion(agente, sub_id: str) -> str:
    """Retrieves and caches human-readable subscription name from Azure."""
    if not hasattr(agente, "_sub_names_cache"):
        agente._sub_names_cache = {}
    if sub_id in agente._sub_names_cache:
        return agente._sub_names_cache[sub_id]
    try:
        kql = "resourcecontainers | where type == 'microsoft.resources/subscriptions' | project name, subscriptionId"
        res = agente.azure.query_azure_resource_graph(kql, bypass_cache=False, subscriptions=[])
        for r in res:
            agente._sub_names_cache[r.get("subscriptionId")] = r.get("name")
    except Exception as e:
        print(f"Error caching subscription names: {e}")
    return agente._sub_names_cache.get(sub_id, "Suscripción Azure")


def buscar_recursos(agente, query_str: str, limit: int = 25, subscriptions: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Searches resources directly in Azure Resource Graph in real-time."""
    if not agente.azure.azure_connected:
        return []

    try:
        # Escape single quotes in query
        query_escaped = query_str.replace("'", "\\'")

        # KQL query supporting fuzzy search on name, type, and RG
        kql = (
            f"resources "
            f"| where name contains '{query_escaped}' "
            f"   or type contains '{query_escaped}' "
            f"   or resourceGroup contains '{query_escaped}' "
            f"| limit {limit} "
            f"| project id, name, type, resourceGroup, subscriptionId, location, tags, sku, properties, kind"
        )
        raw_results = agente.azure.query_azure_resource_graph(kql, subscriptions=subscriptions)

        formatted = []
        for r in raw_results:
            tags_dict = r.get('tags', {}) or {}

            # Tags obligatorias (config.MANDATORY_TAGS), sin distinguir mayúsculas
            tags_lower = {k.lower(): v for k, v in tags_dict.items() if v}
            missing_tags = [t for t in config.MANDATORY_TAGS if t.lower() not in tags_lower]

            owner = tags_dict.get('owner', tags_dict.get('Owner', tags_dict.get('OWNER', '')))
            env = tags_dict.get('environment', tags_dict.get('Environment', tags_dict.get('ENVIRONMENT', '')))
            prov = tags_dict.get('provisioning_method', tags_dict.get('provisioned_by', 'portal'))

            tagging_ok = "Si" if not missing_tags else "No"
            tagging_details = "Cumple" if tagging_ok == "Si" else f"Faltan: {', '.join(missing_tags)}"

            formatted.append({
                "id": r.get('id'),
                "name": r.get('name'),
                "type": r.get('type'),
                "resourceGroup": r.get('resourceGroup'),
                "subscription_name": agente.get_subscription_name(r.get('subscriptionId')),
                "subscriptionId": r.get('subscriptionId'),
                "location": r.get('location'),
                "environment": env or 'Desconocido',
                "owner_confirmed": owner or 'Sin tag owner',
                "provisioning_method": prov,
                "requires_terraform_import": "Si" if prov.lower() != 'terraform' else "No",
                "candidate_module": "azurerm_" + r.get('type').split('/')[-1].lower(),
                "tagging_ok": tagging_ok,
                "tagging_details": tagging_details,
                "missing_tags": missing_tags,
                "tags": json.dumps(tags_dict),
                "sku": r.get('sku') or {},
                "properties": r.get('properties') or {},
                "kind": r.get('kind') or ''
            })
        return formatted
    except Exception as e:
        print(f"Error during search: {e}")
        return []


def reporte_de_costo_de_grupo(agente, rg_name: str, subscriptions: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Costo de un grupo de recursos, tomado de la misma fuente que el panel.

    Este reporte era el ultimo punto de la plataforma donde se publicaban
    cifras inventadas. Sumaba estimaciones por SKU y las entregaba en la
    clave `actual_cost_management` —el nombre del gasto facturado—; si Cost
    Management no respondia, presentaba el total x 1.2 como "pronostico"; y
    tenia ademas una tabla sembrada con importes fijos para un grupo de
    recursos concreto. El resultado era que la misma pregunta daba un numero
    en el chat y otro en el panel, sin que nada indicara cual era real.

    Ahora el gasto facturado viene de CostService —la misma instancia, la
    misma cache precargada y la misma regla por recurso que usa FinOps— y la
    estimacion por SKU cubre solo las suscripciones sin permisos de Cost
    Management, siempre marcada como estimacion en `cost_basis`.
    """
    vacio = {
        "resource_group": rg_name,
        "total_resources_count": 0,
        "cost_basis": "unavailable",
        "coverage_note": "No hay conexión con Azure, así que no se pudo consultar el grupo.",
        "currency": "USD",
        "billed_monthly_cost_usd": 0.0,
        "estimated_monthly_cost_usd": 0.0,
        "total_monthly_cost_usd": 0.0,
        "cost_by_type": {},
        "top_expensive_resources": [],
        "all_resources_summary": [],
    }
    if not agente.azure.azure_connected:
        return vacio

    rg_escaped = rg_name.replace("'", "\\'")
    consulta = (
        f"resources | where resourceGroup =~ '{rg_escaped}' | limit 500 "
        "| project id, name, type, location, tags, sku, properties, kind, subscriptionId"
    )
    recursos = agente.azure.query_azure_resource_graph(consulta, subscriptions=subscriptions) or []
    if not recursos:
        return {
            **vacio,
            "coverage_note": (
                f"El grupo '{rg_name}' no tiene recursos en las suscripciones consultadas."
            ),
        }

    subs_del_grupo = sorted({
        r.get("subscriptionId") for r in recursos if r.get("subscriptionId")
    })

    # `costs_for` sirve primero de lo que ya dejo la precarga en segundo
    # plano, aunque la haya cacheado bajo el scope de todas las
    # suscripciones. Consultar aqui el costo de una sola suscripcion no
    # acertaria en esa entrada y competiria con la precarga por la cuota de
    # Cost Management, que responde 429 con facilidad: el chat acabaria
    # dando una estimacion del mismo grupo que el panel muestra facturado.
    datos_costo: Dict[str, Any] = {}
    try:
        if subs_del_grupo:
            datos_costo = agente._get_cost().costs_for(subs_del_grupo)
    except Exception as exc:
        print(f"[Agent] No se pudo consultar el costo facturado del grupo {rg_name}: {exc}")

    cobertura = datos_costo.get("coverage") or {}
    cubiertas = set(cobertura.get("covered", []))
    cost_map = datos_costo.get("costs") or {}
    ventana = datos_costo.get("window_days") or cost_service.DEFAULT_WINDOW_DAYS
    moneda = datos_costo.get("currency") or "USD"

    # Misma regla que el panel: la decision facturado/estimado se toma
    # recurso por recurso, segun si su suscripcion tiene permisos de costo.
    totales = cost_service.attach_costs(
        recursos, cost_map, ventana, cubiertas, agente.estimate_resource_cost
    )

    por_tipo: Dict[str, float] = {}
    por_recurso: List[Dict[str, Any]] = []
    medidos = 0
    for r in recursos:
        costo = r.get("monthly_cost_usd", 0.0)
        base = r.get("cost_basis", "estimated")
        if base == "actual":
            medidos += 1

        tipo = r.get("type", "Other")
        por_tipo[tipo] = round(por_tipo.get(tipo, 0.0) + costo, 2)

        sku = r.get("sku") or {}
        sku_nombre = sku.get("name") or ""
        sku_tier = sku.get("tier") or ""
        sku_desc = (
            f"{sku_nombre} ({sku_tier})" if sku_nombre and sku_tier
            else (sku_nombre or sku_tier or "Standard")
        )

        por_recurso.append({
            "name": r.get("name"),
            "type": tipo,
            "sku": sku_desc,
            "location": r.get("location"),
            "monthly_cost_usd": round(costo, 2),
            "cost_basis": base,
        })

    por_recurso.sort(key=lambda x: x["monthly_cost_usd"], reverse=True)

    horas = int((datos_costo.get("cache_age_seconds") or 0) // 3600)
    antiguedad = (
        f" El dato viene de la última consolidación de Cost Management, de hace {horas} h."
        if horas >= 1 else ""
    )

    if medidos == len(recursos):
        base_global = "billed"
        nota = (
            f"Gasto facturado por Azure Cost Management sobre los últimos {ventana} días, "
            "normalizado a un mes. Cubre los recursos del grupo en su totalidad." + antiguedad
        )
    elif medidos:
        base_global = "partial"
        nota = (
            f"{medidos} de {len(recursos)} recursos tienen gasto facturado "
            f"(últimos {ventana} días, normalizado a un mes); el resto está en suscripciones "
            "sin permisos de Cost Management y lleva costo estimado por SKU." + antiguedad
        )
    else:
        base_global = "estimated"
        nota = (
            "Ningún recurso del grupo tiene gasto facturado disponible: la cifra es una "
            "estimación por SKU con precios de referencia, no lo que Azure va a cobrar."
        )

    return {
        "resource_group": rg_name,
        "total_resources_count": len(recursos),
        "currency": moneda,
        # 'billed' = todo facturado, 'partial' = mezcla, 'estimated' = todo estimado.
        "cost_basis": base_global,
        "coverage_note": nota,
        "billed_resources_count": medidos,
        "billed_monthly_cost_usd": totales["actual"],
        "estimated_monthly_cost_usd": totales["estimated"],
        "total_monthly_cost_usd": totales["total"],
        "cost_window_days": ventana,
        "cost_by_type": por_tipo,
        "top_expensive_resources": por_recurso[:30],
        "all_resources_summary": [
            {
                "name": x["name"],
                "type": x["type"],
                "monthly_cost_usd": x["monthly_cost_usd"],
                "cost_basis": x["cost_basis"],
            }
            for x in por_recurso
        ],
    }

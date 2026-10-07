import os
import re
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional
import google.generativeai as genai

from app.core import config
from app.providers.azure import AzureClient
from app.services import cost_service, governance, kql, pricing

# El .env lo carga app.core.config (respeta CLOUDOPS_SKIP_DOTENV).

# Setup Gemini API if available
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    HAS_GEMINI = True
else:
    HAS_GEMINI = False

# Instruccion que se añade a los tres agentes. El contexto viaja acotado (ver
# `_acotar_contexto`), asi que el modelo tiene que saber distinguir una lista
# completa de una muestra: sin esto seguiria las reglas previas —que le pedian
# afirmar que el listado es el total— y presentaria como inventario completo lo
# que es solo la primera pagina.
REGLA_LISTAS_ACOTADAS = (
    "COMO LEER EL CONTEXTO (REGLA CRÍTICA):\n"
    "Las listas del contexto pueden llegar de dos formas. Si es una lista normal, "
    "esta completa: preséntala como el total registrado en Azure y no hables de "
    "muestreo. Si en cambio es un objeto con las claves 'muestra', 'total' y "
    "'truncado', entonces solo tienes los primeros elementos: usa 'total' para dar "
    "la cifra exacta —que si es fiable— y di con naturalidad que estas mostrando "
    "los primeros N de ese total, ofreciendo acotar la busqueda para ver el resto. "
    "Nunca completes una lista truncada con recursos inventados ni presentes la "
    "muestra como si fuera el inventario entero.\n"
    "El campo 'consultas_incompletas', si aparece, enumera las consultas que no "
    "alcanzaron a responder: para esos temas debes decir que el dato no esta "
    "disponible en esta respuesta, en lugar de concluir que no hay hallazgos."
)


class AzureInventoryAgent:
    def __init__(self, azure: Optional[AzureClient] = None):
        # Todo acceso a Azure pasa por el cliente; el agente solo arma
        # contexto y conversa.
        self.azure = azure if azure is not None else AzureClient()

        # Servicios de dominio. main.py inyecta con attach_services las mismas
        # instancias que alimentan el panel, para que el chat comparta su cache
        # —incluida la precarga de costos— y, sobre todo, para que responda con
        # las mismas reglas. Si nadie los inyecta se crean bajo demanda, de modo
        # que el agente siga siendo utilizable por si solo en pruebas.
        self._secops = None
        self._finops = None
        self._cost = None
        self._risk = None

    def attach_services(self, secops=None, finops=None, cost=None, risk=None) -> None:
        """Comparte con el agente los servicios que ya usa el panel."""
        if secops is not None:
            self._secops = secops
        if finops is not None:
            self._finops = finops
        if cost is not None:
            self._cost = cost
        if risk is not None:
            self._risk = risk

    def _get_secops(self):
        if self._secops is None:
            from app.services.secops_service import SecOpsService

            self._secops = SecOpsService(self.azure)
        return self._secops

    def _get_cost(self):
        """
        CostService compartido con el panel.

        Importa que sea la misma instancia: su cache es la que llena la precarga
        en segundo plano, de modo que el chat responde con el gasto ya
        consolidado en vez de disparar consultas a Cost Management —que limita
        con dureza— mientras el usuario espera la respuesta.
        """
        if self._cost is None:
            from app.services.cost_service import CostService

            self._cost = CostService(self.azure)
        return self._cost


    def get_summary_stats(self, subscriptions: Optional[List[str]] = None) -> Dict[str, Any]:
        """Calculates current statistics of the Azure Subscription in real-time."""
        if not self.azure.azure_connected:
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
                f_stats = executor.submit(self.azure.query_azure_resource_graph, kql_stats, False, subscriptions)
                
                # 2. Terraform-managed
                # La evidencia de IaC sale de services/governance.py, igual que
                # en el inventario. Antes esta consulta miraba solo tres claves
                # con el valor exacto 'terraform', asi que daba una cobertura
                # distinta a la del panel sobre el mismo tenant.
                f_tf = executor.submit(
                    self.azure.query_azure_resource_graph,
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
                    self.azure.query_azure_resource_graph,
                    "resources | summarize count() by type | order by count_ desc | limit 6",
                    False,
                    subscriptions
                )
                
                # 4. Subscription distribution
                f_subs = executor.submit(
                    self.azure.query_azure_resource_graph,
                    "resources | summarize count() by subscriptionId | limit 5",
                    False,
                    subscriptions
                )
                
                # 5. Unattached Disks
                f_disks = executor.submit(
                    self.azure.query_azure_resource_graph,
                    "resources | where type =~ 'microsoft.compute/disks' and properties.diskState =~ 'Unattached' | summarize count()",
                    False,
                    subscriptions
                )
                
                # 6. Unassociated Public IPs
                f_ips = executor.submit(
                    self.azure.query_azure_resource_graph,
                    "resources | where type =~ 'microsoft.network/publicipaddresses' and isnull(properties.ipConfiguration) | summarize count()",
                    False,
                    subscriptions
                )
                
                # 7. Orphaned Network Interfaces
                f_nics = executor.submit(
                    self.azure.query_azure_resource_graph,
                    "resources | where type =~ 'microsoft.network/networkinterfaces' and isnull(properties.virtualMachine) | summarize count()",
                    False,
                    subscriptions
                )
                
                # 8. Exposed NSGs
                f_nsgs = executor.submit(
                    self.azure.query_azure_resource_graph,
                    "resources | where type =~ 'microsoft.network/networksecuritygroups' | mv-expand rules=properties.securityRules | where rules.properties.direction =~ 'Inbound' and rules.properties.access =~ 'Allow' and (rules.properties.destinationPortRange in ('22', '3389', '*') or rules.properties.destinationPortRanges has '22' or rules.properties.destinationPortRanges has '3389') and (rules.properties.sourceAddressPrefix in ('*', '0.0.0.0/0', 'Internet') or rules.properties.sourceAddressPrefixes has '*' or rules.properties.sourceAddressPrefixes has 'Internet') | summarize count()",
                    False,
                    subscriptions
                )
                
                # 9. Failed resources
                f_failed = executor.submit(
                    self.azure.query_azure_resource_graph,
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
                limite_kpis = time.monotonic() + self.PRESUPUESTO_KPIS_SEGUNDOS
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

    def get_subscription_name(self, sub_id: str) -> str:
        """Retrieves and caches human-readable subscription name from Azure."""
        if not hasattr(self, "_sub_names_cache"):
            self._sub_names_cache = {}
        if sub_id in self._sub_names_cache:
            return self._sub_names_cache[sub_id]
        try:
            kql = "resourcecontainers | where type == 'microsoft.resources/subscriptions' | project name, subscriptionId"
            res = self.azure.query_azure_resource_graph(kql, bypass_cache=False, subscriptions=[])
            for r in res:
                self._sub_names_cache[r.get("subscriptionId")] = r.get("name")
        except Exception as e:
            print(f"Error caching subscription names: {e}")
        return self._sub_names_cache.get(sub_id, "Suscripción Azure")

    def search_resources(self, query_str: str, limit: int = 25, subscriptions: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Searches resources directly in Azure Resource Graph in real-time."""
        if not self.azure.azure_connected:
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
            raw_results = self.azure.query_azure_resource_graph(kql, subscriptions=subscriptions)
            
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
                    "subscription_name": self.get_subscription_name(r.get('subscriptionId')),
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

    def estimate_resource_cost(self, r: Dict[str, Any]) -> float:
        """
        Estimacion mensual de un recurso por tipo y SKU.

        La tabla de tarifas vive en services/pricing.py, que es tambien la que
        alimenta el respaldo de FinOps y el prompt del agente: antes existian
        tres copias y ya diferian entre si.
        """
        return pricing.costo_mensual_estimado(r)

    def generate_rg_cost_report(self, rg_name: str, subscriptions: Optional[List[str]] = None) -> Dict[str, Any]:
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
        if not self.azure.azure_connected:
            return vacio

        rg_escaped = rg_name.replace("'", "\\'")
        consulta = (
            f"resources | where resourceGroup =~ '{rg_escaped}' | limit 500 "
            "| project id, name, type, location, tags, sku, properties, kind, subscriptionId"
        )
        recursos = self.azure.query_azure_resource_graph(consulta, subscriptions=subscriptions) or []
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
                datos_costo = self._get_cost().costs_for(subs_del_grupo)
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
            recursos, cost_map, ventana, cubiertas, self.estimate_resource_cost
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

    def _responder_con_reglas(
        self, question: str, agent_type: str, subscriptions: Optional[List[str]]
    ) -> Dict[str, Any]:
        """Motor de reglas por agente: costos y seguridad responden con sus servicios."""
        from app.agents import rule_answers

        try:
            if agent_type == "finops":
                return rule_answers.respuesta_finops(self, question, subscriptions)
            if agent_type == "secops":
                return rule_answers.respuesta_secops(self, subscriptions)
        except Exception as exc:
            print(f"[Agente] Respuesta por reglas de {agent_type} fallo: {exc}")
        return self.ask_rule_based(question)

    def ask_rule_based(self, question: str) -> Dict[str, Any]:
        """Offline and rule-based fallback answering engine using direct KQL queries."""
        if not self.azure.azure_connected:
            return {
                "answer": "⚠️ **Error de Conexión:** No estoy conectado a Azure. Revisa tus llaves del Service Principal en el archivo `.env` para habilitar las consultas en tiempo real.",
                "mode": "offline",
                "data": []
            }
            
        question_lower = question.lower()
        
        # Rule: Questions about savings, technical debt lifecycle, and exceptions - disabled
        if any(w in question_lower for w in ["deuda", "deuda técnica", "excepción", "excepciones", "remediado", "aprobado"]):
            return {
                "answer": "El módulo de Gestión de Recomendaciones y Deuda Operacional se encuentra inhabilitado en esta plataforma por decisión administrativa. Si deseas realizar optimizaciones, por favor consulta al equipo SRE.",
                "mode": "azure_live_rule_fallback",
                "data": []
            }

        # 1. Ask about a specific resource name
        # El conector opcional (de/del/of) evita capturarlo como nombre del recurso:
        # "¿quién es el dueño de kv-x?" debe buscar `kv-x`, no `de`.
        resource_match = re.search(r'(?:dueño|owner|detalles|dónde está|donde esta|recurso)(?:\s+(?:de|del|of))?\s+([a-zA-Z0-9\-_.]+)', question_lower)
        if resource_match:
            resource_name = resource_match.group(1)
            kql = f"resources | where name =~ '{resource_name}' | project name, type, resourceGroup, subscriptionId, location, tags"
            raw = self.azure.query_azure_resource_graph(kql)
            
            if raw:
                res = raw[0]
                tags = res.get('tags', {}) or {}
                owner = tags.get('owner', tags.get('Owner', tags.get('OWNER', '❌ Sin tag owner')))
                env = tags.get('environment', tags.get('Environment', tags.get('ENVIRONMENT', 'Sin tag environment')))
                prov = tags.get('provisioning_method', tags.get('provisioned_by', 'portal (manual)'))
                
                md_resp = (
                    f"### 🔍 Recurso Encontrado en Tiempo Real (Azure):\n\n"
                    f"• **Nombre:** `{res['name']}`\n"
                    f"• **Tipo:** `{res['type']}`\n"
                    f"• **Dueño:** `{owner}`\n"
                    f"• **Ambiente:** `{env}`\n"
                    f"• **Resource Group:** `{res['resourceGroup']}`\n"
                    f"• **Ubicación (Región):** `{res['location']}`\n"
                    f"• **Método de Provisión:** `{prov.upper()}`\n"
                    f"• **ID Suscripción:** `{res['subscriptionId']}`\n"
                )
                
                return {"answer": md_resp, "mode": "azure_live", "data": raw}
            else:
                # Si el usuario pregunta por diagnóstico, fallos o remediación de red de un recurso que no existe
                if any(w in question_lower for w in ["diagnosticar", "remediar", "failed", "fallado", "puerto", "nsg", "seguridad", "causas"]):
                    # Responder teóricamente según el tipo o contexto
                    if "nsg" in question_lower or "puerto" in question_lower:
                        md_resp = (
                            f"### 🛡️ Guía de Remediación de NSG (Teórica):\n\n"
                            f"El recurso `{resource_name}` no figura en el inventario real de Azure, pero para remediar reglas de NSG expuestas, sigue estos pasos:\n\n"
                            f"1. **Comando de Remediación (Azure CLI):**\n"
                            f"   ```bash\n"
                            f"   az network nsg rule update \\\n"
                            f"     --resource-group <mi-grupo-recursos> \\\n"
                            f"     --nsg-name <nombre-nsg> \\\n"
                            f"     --name <nombre-regla-SSH-RDP> \\\n"
                            f"     --source-address-prefixes <IP_Corporativa_Permitida> \\\n"
                            f"     --direction Inbound \\\n"
                            f"     --access Allow\n"
                            f"   ```\n"
                            f"2. **Procedimiento Recomendado:** Restringe el origen `*` o `0.0.0.0/0` a una VPN corporativa o Azure Bastion para mitigar riesgos de intrusión."
                        )
                    else:  # Asumimos máquina virtual en estado Failed
                        md_resp = (
                            f"### ❌ Diagnóstico de Máquina Virtual en estado Failed (Teórico):\n\n"
                            f"El recurso `{resource_name}` no figura en el inventario real de Azure, pero para una máquina virtual (`microsoft.compute/virtualmachines`) en estado **Failed**, las causas más comunes y su diagnóstico son:\n\n"
                            f"1. **Causas Comunes de Failed State:**\n"
                            f"   - **Fallo de aprovisionamiento de extensiones:** Una extensión de Azure (ej. log analytics, network watcher, etc.) falló al instalarse o se colgó en el script de arranque.\n"
                            f"   - **Falta de recursos en el hipervisor (Allocation Failure):** Azure no encontró suficiente capacidad física en la región para arrancar el tamaño de VM solicitado.\n"
                            f"   - **Problemas en el arranque del OS:** Fallo en el sysprep o en la inicialización de los discos de boot.\n\n"
                            f"2. **Procedimiento de Diagnóstico & Remediación:**\n"
                            f"   * **Paso 1: Forzar una actualización de estado (Redeploy/Reapply):**\n"
                            f"     Esto limpia el estado transitorio fallido de Kudu/ARM sin borrar datos:\n"
                            f"     ```bash\n"
                            f"     az vm reapply --resource-group <mi-grupo-recursos> --name {resource_name}\n"
                            f"     ```\n"
                            f"   * **Paso 2: Comprobar los Logs de Aprovisionamiento:**\n"
                            f"     ```bash\n"
                            f"     az vm get-instance-view --resource-group <mi-grupo-recursos> --name {resource_name} --query \"instanceView.statuses\"\n"
                            f"     ```\n"
                            f"   * **Paso 3: Reiniciar o Redesplegar en otro host físico:**\n"
                            f"     ```bash\n"
                            f"     az vm redeploy --resource-group <mi-grupo-recursos> --name {resource_name}\n"
                            f"     ```"
                        )
                    return {"answer": md_resp, "mode": "offline_diagnostic_fallback", "data": []}
                
                return {
                    "answer": f"No encontré ningún recurso con el nombre `{resource_name}` en las suscripciones a las que tiene acceso el Service Principal.",
                    "mode": "azure_live",
                    "data": []
                }

        # 2. Tag Gaps / Policy violations
        if any(w in question_lower for w in ["tags", "políticas", "politica", "compliance", "gaps", "incumplen", "cumplen", "sin tag"]):
            kql_gaps = (
                "resources "
                + governance.kql_extends_tags_presentes(config.MANDATORY_TAGS)
                + f"| where not({governance.kql_todas_presentes(config.MANDATORY_TAGS)}) "
                "| limit 5 "
                "| project name, type, resourceGroup, tags"
            )
            raw_gaps = self.azure.query_azure_resource_graph(kql_gaps)
            stats = self.get_summary_stats()
            
            md_resp = (
                f"### 📋 Auditoría de Tags en Tiempo Real\n\n"
                f"• Cumplimiento Global de Tags: **{stats['tag_compliance_percentage']}%** de recursos cumpliendo.\n"
                f"• Recursos con incumplimiento: **{stats['missing_owner_tags']}** recursos (les falta al menos una de las {len(config.MANDATORY_TAGS)} etiquetas obligatorias).\n\n"
            )
            
            if 'missing_tags_detail' in stats:
                md_resp += "#### 📊 Conteo de etiquetas faltantes por categoría:\n"
                for tag_name, count in stats['missing_tags_detail'].items():
                    md_resp += f"- Tag **{tag_name}**: Faltante en **{count}** recursos\n"
                md_resp += "\n"
                
            if raw_gaps:
                md_resp += "#### ⚠️ Recursos no cumplidores (Muestra):\n"
                for r in raw_gaps:
                    tags = r.get('tags', {}) or {}
                    tags_lower = {k.lower(): v for k, v in tags.items() if v}
                    missing = [t for t in config.MANDATORY_TAGS if t.lower() not in tags_lower]
                    md_resp += f"- `{r['name']}` ({r['type'].split('/')[-1]}) | RG: `{r['resourceGroup']}` | Faltan: {', '.join(missing)}\n"
            else:
                md_resp += "🎉 ¡Excelente! Todos los recursos analizados cumplen con las políticas de las " + str(len(config.MANDATORY_TAGS)) + " etiquetas obligatorias."
                
            return {"answer": md_resp, "mode": "azure_live", "data": raw_gaps}

        # 3. Terraform Adoption / Shadow IT
        if any(w in question_lower for w in ["terraform", "importar", "por fuera", "portal", "manual", "shadow"]):
            # Mismo criterio que el panel: sin evidencia de IaC y sin ser un
            # recurso derivado de otro. La version anterior negaba dos claves
            # con `!=`, que en KQL ni siquiera es lo contrario de la condicion
            # que contaba los gestionados, de modo que las dos cifras de la
            # misma respuesta se contradecian.
            kql_manual = (
                "resources "
                "| extend _t = todynamic(tolower(tostring(tags))) "
                "| extend _json = tolower(tostring(tags)) "
                f"| where not({governance.kql_tiene_iac()}) "
                f"| where not({governance.kql_es_derivado()}) "
                "| limit 5 "
                "| project name, type, resourceGroup, tags"
            )
            raw_manual = self.azure.query_azure_resource_graph(kql_manual)
            stats = self.get_summary_stats()
            
            md_resp = (
                f"### 🛠️ Auditoría de Cobertura IaC / Terraform\n\n"
                f"• Recursos administrados con Terraform: `{stats['terraform_managed']}` ({stats['terraform_percentage']}%)\n"
                f"• Recursos provistos vía Portal/Manual/Otros: `{stats['portal_managed']}` recursos\n\n"
            )
            
            if raw_manual:
                md_resp += "#### 📌 Recursos creados por fuera de Terraform (Muestra):\n"
                for r in raw_manual:
                    md_resp += f"- **`{r['name']}`** ({r['type'].split('/')[-1]}) en RG: `{r['resourceGroup']}`\n"
            else:
                md_resp += "🎉 ¡Excelente! Toda tu infraestructura está bajo el control de Terraform."
                
            return {"answer": md_resp, "mode": "azure_live", "data": raw_manual}

        # 4. Summary / Resumen
        if any(w in question_lower for w in ["resumen", "estadisticas", "inventario", "cuantos recursos", "total"]):
            stats = self.get_summary_stats()
            md_resp = (
                f"### 📊 Resumen Ejecutivo del Inventario de Azure (Live)\n\n"
                f"• **Total recursos descubiertos:** `{stats['total_resources']}`\n"
                f"• **Cumplimiento global de tags:** {stats['tag_compliance_percentage']}%\n\n"
                f"**Top Tipos de Recursos:**\n"
            )
            for rtype, count in list(stats['domain_distribution'].items())[:4]:
                md_resp += f"- *{rtype}:* {count} recursos\n"
                
            return {"answer": md_resp, "mode": "azure_live", "data": [stats]}
 
        # Generic search fallback
        matches = self.search_resources(question, limit=5)
        if matches:
            md_resp = "Encontré los siguientes recursos que coinciden con tu consulta:\n\n"
            for r in matches:
                md_resp += f"- **`{r['name']}`** ({r['type'].split('/')[-1]}) | Owner: `{r['owner_confirmed']}` | RG: `{r['resourceGroup']}`\n"
            return {"answer": md_resp, "mode": "azure_live", "data": matches}
            
        return {
            "answer": "No logré interpretar tu pregunta. Intenta consultarme sobre:\n"
                      "- *¿Quién es el dueño del recurso [nombre]?*\n"
                      "- *¿Qué recursos no cumplen las políticas de tags?*\n"
                      "- *Resumen del inventario*",
            "mode": "azure_live",
            "data": []
        }

    @staticmethod
    def _tags_como_dict(tags: Any) -> Dict[str, Any]:
        """
        Normaliza los tags de un recurso, vengan como diccionario o serializados.

        Un recurso sin tags llega como la cadena `"null"` —`search_resources`
        hace `json.dumps(None)`— y `json.loads` la convierte de vuelta en `None`,
        no en un diccionario. El codigo que seguia llamaba `.items()` sobre ese
        `None` y reventaba dentro del `try` general de `ask()`, que lo
        interpretaba como un fallo del modelo y respondia con el motor de
        reglas. Es decir: bastaba un solo recurso sin etiquetar en la muestra
        —lo habitual— para que el agente dejara de usar IA sin decirlo.
        """
        if isinstance(tags, dict):
            return tags
        if isinstance(tags, str):
            try:
                cargado = json.loads(tags)
            except Exception:
                return {}
            return cargado if isinstance(cargado, dict) else {}
        return {}

    # ------------------------------------------------------------------
    # Presupuesto de contexto
    # ------------------------------------------------------------------
    #
    # El contexto viajaba entero al modelo: `json.dumps(indent=2)` de un
    # diccionario que incluia listas completas del tenant —todas las IPs
    # publicas, todas las VMs, todos los grupos de recursos— mas hasta 500
    # recursos con sus propiedades. En un tenant de 3.700 recursos eso son
    # cientos de miles de tokens por pregunta: caro, lento y, sobre todo, peor
    # respondido, porque la señal se diluye entre paginas de datos que nadie
    # pidio.
    #
    # Ahora cada lista viaja acotada y declara cuanto se quedo fuera, de modo
    # que el agente puede decir "hay 212, te muestro 15" en vez de inventar o de
    # dar por completa una lista truncada en silencio.
    MUESTRA_POR_LISTA = 15
    MAX_RECURSOS_DE_RG = 60
    MAX_GRUPOS_DE_RECURSOS = 40
    MAX_HALLAZGOS = 30

    @staticmethod
    def _acotar(valor: Any, limite: int) -> Any:
        """Recorta una lista dejando constancia de cuantos elementos tenia."""
        if not isinstance(valor, list) or len(valor) <= limite:
            return valor
        return {
            "muestra": valor[:limite],
            "total": len(valor),
            "truncado": True,
            "nota": (
                f"Se incluyen {limite} de {len(valor)} elementos. "
                "El total es exacto; para ver el resto hay que acotar la pregunta."
            ),
        }

    def _acotar_contexto(
        self, context_data: Dict[str, Any], question: str
    ) -> Dict[str, Any]:
        """
        Aplica el presupuesto a todo el contexto antes de serializarlo.

        Los grupos de recursos reciben trato aparte: en lugar de mandar los
        cientos que tiene el tenant, viajan los que la pregunta menciona mas una
        muestra, porque su utilidad es que el agente reconozca el nombre que el
        usuario escribio.
        """
        acotado: Dict[str, Any] = {}
        pregunta = (question or "").lower()

        for clave, valor in context_data.items():
            if clave == "all_resource_groups" and isinstance(valor, list):
                mencionados = [rg for rg in valor if rg and rg.lower() in pregunta]
                resto = [rg for rg in valor if rg not in mencionados]
                seleccion = mencionados + resto[: self.MAX_GRUPOS_DE_RECURSOS]
                acotado[clave] = (
                    seleccion
                    if len(valor) <= self.MAX_GRUPOS_DE_RECURSOS
                    else {
                        "muestra": seleccion,
                        "total": len(valor),
                        "truncado": True,
                        "nota": (
                            "Incluye los grupos de recursos citados en la pregunta "
                            f"mas una muestra; el tenant tiene {len(valor)}."
                        ),
                    }
                )
            elif clave == "target_resource_group_resources":
                acotado[clave] = self._acotar(valor, self.MAX_RECURSOS_DE_RG)
            elif clave == "security_findings":
                # Vienen ordenados por severidad, asi que el recorte conserva
                # siempre lo mas grave primero.
                acotado[clave] = self._acotar(valor, self.MAX_HALLAZGOS)
            elif clave == "relevant_resources_sample":
                acotado[clave] = self._acotar(valor, self.MUESTRA_POR_LISTA)
            else:
                acotado[clave] = self._acotar(valor, self.MUESTRA_POR_LISTA)

        return acotado

    # Presupuesto total que la recoleccion de contexto puede gastar esperando a
    # Azure. Antes cada consulta tenia su propio `timeout=8`, resueltos en serie:
    # trece consultas podian sumar mas de cien segundos, peligrosamente cerca del
    # corte de 230s del gateway de App Service. El limite ahora es del conjunto.
    PRESUPUESTO_CONTEXTO_SEGUNDOS = 25.0

    # Limite total de las nueve consultas que producen los KPIs del panel.
    PRESUPUESTO_KPIS_SEGUNDOS = 15.0

    def _contexto_de_dominio(
        self, agent_type: str, subscriptions: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Datos del dominio del agente, tomados de las mismas fuentes que el panel.

        SecOps delega en SecOpsService: asi el chat hereda las consultas
        corregidas y la severidad por alcanzabilidad, en vez de la copia paralela
        que tenia el agente —la que marcaba el 96% de las cuentas de
        almacenamiento como expuestas y todos los Key Vaults del tenant—. FinOps
        usa el catalogo compartido de consultas (services/kql.py).
        """
        if agent_type == "secops":
            # Si el servicio de riesgo esta disponible, los hallazgos llegan ya
            # cruzados con el gasto del recurso expuesto y ordenados por
            # severidad y dinero: el chat prioriza igual que el panel.
            try:
                if self._risk is not None:
                    reporte = self._risk.build_report(subscriptions or [])
                    reporte["exposure"] = {
                        "by_severity": reporte.get("exposure_by_severity", {}),
                        "top": reporte.get("top_exposure", []),
                        "totals": reporte.get("totals", {}),
                        "coverage": reporte.get("coverage", {}),
                    }
                else:
                    reporte = self._get_secops().build_report(subscriptions or [])
            except Exception as exc:
                print(f"Error construyendo el contexto de SecOps: {exc}")
                return {}
            # `findings` ya contiene, con severidad y recomendacion, los mismos
            # elementos que las listas por tipo del panel: mandar ambas cosas
            # duplicaba el contexto sin añadir un solo dato. Las IPs publicas
            # activas si viajan aparte, porque son superficie de ataque y no
            # hallazgos: el reporte las cuenta pero no las clasifica.
            contexto = {
                "security_findings": reporte.get("findings", []),
                "severity_summary": reporte.get("severity_summary", {}),
                "attack_surface_summary": reporte.get("attack_surface_summary", {}),
                "public_ips_active_list": reporte.get("public_ips_active", []),
            }
            if reporte.get("exposure"):
                contexto["cost_exposure"] = reporte["exposure"]
            return contexto

        if agent_type == "finops":
            consultas = {
                "unattached_disks_list": kql.DISCOS_HUERFANOS,
                "unassociated_ips_list": kql.IPS_SIN_ASOCIAR,
                "orphaned_nics_list": kql.NICS_HUERFANAS,
                "empty_app_plans_list": kql.APP_PLANS_VACIOS,
                "old_snapshots_list": kql.SNAPSHOTS,
                "untagged_resources_list": kql.recursos_sin_tags(25),
                "resources_by_rg": kql.RECURSOS_POR_RG,
            }
            return self._ejecutar_en_paralelo(consultas, subscriptions)

        return {}

    def _ejecutar_en_paralelo(
        self, consultas: Dict[str, str], subscriptions: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Lanza varias consultas KQL a la vez y espera, en total, lo que marque
        `PRESUPUESTO_CONTEXTO_SEGUNDOS`.

        Una consulta que se pase de tiempo devuelve lista vacia y se anota, en
        lugar de tumbar el resto: antes, cualquier expiracion vaciaba todas las
        listas a la vez y el agente respondia como si el tenant estuviera vacio.
        """
        resultados: Dict[str, Any] = {nombre: [] for nombre in consultas}
        incompletas: List[str] = []

        with ThreadPoolExecutor(max_workers=max(1, len(consultas))) as executor:
            futuros = {
                nombre: executor.submit(
                    self.azure.query_azure_resource_graph, consulta, False, subscriptions
                )
                for nombre, consulta in consultas.items()
            }
            limite = time.monotonic() + self.PRESUPUESTO_CONTEXTO_SEGUNDOS
            for nombre, futuro in futuros.items():
                restante = max(0.1, limite - time.monotonic())
                try:
                    resultados[nombre] = futuro.result(timeout=restante) or []
                except Exception as exc:
                    incompletas.append(nombre)
                    print(f"Consulta de contexto '{nombre}' sin resultado: {exc}")

        if incompletas:
            resultados["consultas_incompletas"] = incompletas
        return resultados

    def ask(self, question: str, agent_type: str = "inventory", subscriptions: Optional[List[str]] = None) -> Dict[str, Any]:
        """Processes the natural language query using Gemini (RAG) or Fallback search."""
        if not HAS_GEMINI:
            return self._responder_con_reglas(question, agent_type, subscriptions)
            
        try:
            # ──────────────────────────────────────────────
            # 1 y 2. RECOLECCION DEL CONTEXTO
            # ──────────────────────────────────────────────
            #
            # Las tres etapas corrian en serie y sin tope: sus tiempos se
            # sumaban, y en un tenant grande cada una tarda mucho mas que en
            # desarrollo porque recorre decenas de suscripciones. Ahora van a la
            # vez y comparten un limite; lo que no llegue se declara y el agente
            # responde con lo que tiene en vez de agotar el gateway.
            reloj = time.monotonic()
            tiempos: Dict[str, float] = {}
            etapas = {
                "stats": lambda: self.get_summary_stats(subscriptions=subscriptions) or {},
                "grupos": lambda: self.azure.get_resource_groups(subscriptions=subscriptions) or [],
                "dominio": lambda: self._contexto_de_dominio(agent_type, subscriptions),
            }
            resultados_etapa: Dict[str, Any] = {"stats": {}, "grupos": [], "dominio": {}}
            etapas_incompletas: List[str] = []

            with ThreadPoolExecutor(max_workers=3) as executor:
                lanzadas = {
                    nombre: executor.submit(funcion) for nombre, funcion in etapas.items()
                }
                limite = time.monotonic() + self.PRESUPUESTO_CONTEXTO_SEGUNDOS
                for nombre, futuro in lanzadas.items():
                    marca = time.monotonic()
                    try:
                        resultados_etapa[nombre] = futuro.result(
                            timeout=max(0.1, limite - time.monotonic())
                        )
                    except Exception as exc:
                        etapas_incompletas.append(nombre)
                        print(f"Etapa de contexto '{nombre}' sin resultado: {exc}")
                    tiempos[nombre] = round(time.monotonic() - marca, 1)

            stats = resultados_etapa["stats"]
            rgs = resultados_etapa["grupos"]
            datos_dominio = resultados_etapa["dominio"]
            if etapas_incompletas:
                datos_dominio = dict(datos_dominio)
                datos_dominio.setdefault("consultas_incompletas", []).extend(
                    etapas_incompletas
                )

            # 4. Extract keywords for contextual retrieval
            keywords = re.findall(r'[a-zA-Z0-9\-_]+', question)
            # Filter technical looking keywords (length > 4, or has digit, dash, underscore)
            technical_keywords = []
            for w in keywords:
                w_lower = w.lower()
                if w_lower in [
                    'que', 'quien', 'como', 'para', 'del', 'los', 'las', 'con', 'por', 'una', 'uno', 'unos', 'unas',
                    'este', 'esta', 'estos', 'estas', 'todo', 'todos', 'toda', 'todas', 'sobre', 'donde', 'hacer', 'cuales'
                ]:
                    continue
                if len(w) > 4 or any(c.isdigit() or c in '-_' for c in w):
                    technical_keywords.append(w)
            
            # De-duplicate and prioritize longer words
            technical_keywords = sorted(list(set(technical_keywords)), key=len, reverse=True)
            
            # Limit KQL queries to at most 2 technical keywords
            search_terms = technical_keywords[:2]
            
            relevant_resources = []
            seen = set()
            
            for kw in search_terms:
                matches = self.search_resources(kw, limit=10, subscriptions=subscriptions)
                for m in matches:
                    key = m.get('name', '') + m.get('type', '')
                    if key not in seen:
                        seen.add(key)
                        relevant_resources.append(m)
            
            if not relevant_resources:
                kql = "resources | limit 10 | project name, type, resourceGroup, location, tags, sku, properties, kind"
                raw = self.azure.query_azure_resource_graph(kql, subscriptions=subscriptions)
                for r in raw:
                    relevant_resources.append({
                        "name": r.get('name'),
                        "type": r.get('type'),
                        "resourceGroup": r.get('resourceGroup'),
                        "location": r.get('location'),
                        "tags": json.dumps(r.get('tags', {})),
                        "sku": r.get('sku') or {},
                        "properties": r.get('properties') or {},
                        "kind": r.get('kind') or ''
                    })
            else:
                relevant_resources = relevant_resources[:25]

            # 5. Format the resource sample for the prompt
            formatted_sample = []
            for r in relevant_resources:
                if "tagging_details" in r:
                    tag_comp = r["tagging_details"]
                else:
                    tags_dict = self._tags_como_dict(r.get("tags"))

                    tags_lower = {k.lower(): v for k, v in tags_dict.items() if v}
                    missing_tags = [t for t in config.MANDATORY_TAGS if t.lower() not in tags_lower]
                    tag_comp = "Cumple" if not missing_tags else f"Faltan: {', '.join(missing_tags)}"

                # Extract key pricing metrics to keep context window clean
                sku_data = r.get("sku") or {}
                raw_props = r.get("properties") or {}
                
                # Prune properties to only keep pricing-impactful keys
                pruned_props = {}
                for key in ["serverOS", "operatingSystem", "hardwareProfile", "storageProfile", "capacity", "tier", "sizeName", "serviceLevel", "numberOfSites", "publicNetworkAccess", "allowBlobPublicAccess"]:
                    if key in raw_props:
                        pruned_props[key] = raw_props[key]

                formatted_sample.append({
                    "name": r.get("name"),
                    "type": r.get("type"),
                    "resourceGroup": r.get("resourceGroup"),
                    "subscription_name": r.get("subscription_name", "Azure Subscription"),
                    "location": r.get("location"),
                    "tag_compliance": tag_comp,
                    "sku": sku_data,
                    "pricing_properties": pruned_props,
                    "kind": r.get("kind") or ''
                })

            # Load active operational debt recommendations from local DB - disabled
            db_recommendations = []

            # 5b. Detect if a resource group is mentioned in the user's query
            mentioned_rg = None
            if rgs:
                # Sort RGs by length descending to match the most specific/longest name first
                sorted_rgs = sorted(rgs, key=len, reverse=True)
                for rg in sorted_rgs:
                    if rg.lower() in question.lower():
                        mentioned_rg = rg
                        break

            rg_cost_report = None
            rg_resources = []
            if mentioned_rg:
                print(f"Detected mentioned resource group: {mentioned_rg}. Generating cost report...")
                rg_cost_report = self.generate_rg_cost_report(mentioned_rg, subscriptions=subscriptions)
                
                rg_escaped = mentioned_rg.replace("'", "\\'")
                kql_rg_res = f"resources | where resourceGroup =~ '{rg_escaped}' | limit 500 | project name, type, location, tags, sku, properties, kind"
                raw_rg_res = self.azure.query_azure_resource_graph(kql_rg_res, subscriptions=subscriptions) or []
                for r in raw_rg_res:
                    raw_props = r.get("properties") or {}
                    pruned_props = {}
                    for key in ["serverOS", "operatingSystem", "hardwareProfile", "storageProfile", "capacity", "tier", "sizeName", "serviceLevel", "numberOfSites", "publicNetworkAccess", "allowBlobPublicAccess"]:
                        if key in raw_props:
                            pruned_props[key] = raw_props[key]
                            
                    tags_dict = self._tags_como_dict(r.get('tags'))

                    rg_resources.append({
                        "name": r.get("name"),
                        "type": r.get("type"),
                        "location": r.get("location"),
                        "tags": tags_dict,
                        "sku": r.get("sku") or {},
                        "pricing_properties": pruned_props,
                        "kind": r.get("kind") or ''
                    })

            # 6. Build the unified context (all domains, all agents)
            context_data = {
                "connection_mode": "Azure Live Cloud Connection",
                "agent_type": agent_type,
                "inventory_summary": stats,
                "all_resource_groups": rgs,
                "relevant_resources_sample": formatted_sample,
                "operational_debt_recommendations": db_recommendations,
                "target_resource_group_cost_report": rg_cost_report,
                "target_resource_group_resources": rg_resources,
                # Datos del dominio del agente: hallazgos de seguridad con
                # severidad para SecOps, categorias de desperdicio para FinOps.
                # Las claves las define _contexto_de_dominio.
                **datos_dominio,
            }

            # 7. Agent-specific system prompts (full domain scope)
            if agent_type == "finops":
                system_prompt = (
                    f"Eres el Agente FinOps y Optimización de Costos Cloud de {config.ORG_NAME}. "
                    "Tienes acceso completo y en tiempo real al inventario de la suscripción Azure.\n\n"
                    "Tu alcance completo incluye:\n"
                    "- Recursos huérfanos: discos sin asociar (unattached_disks_list), IPs públicas libres "
                    "(unassociated_ips_list), NICs sin VM (orphaned_nics_list)\n"
                    "- Recursos sobredimensionados: App Service Plans vacíos (empty_app_plans_list), "
                    "VMs potencialmente undersized/oversized\n"
                    "- Activos olvidados: snapshots antiguos (old_snapshots_list), recursos sin ningún tag "
                    "(untagged_resources_list)\n"
                    "- Distribución de costos: recursos por tipo, por grupo de recursos (resources_by_rg), "
                    "por ambiente\n"
                    "- Análisis de gobernanza financiera: cuántos recursos tienen tags de cost allocation\n"
                    "- Recomendaciones de ahorro: estimaciones en USD de lo que se puede ahorrar eliminando "
                    "recursos huérfanos\n"
                    "- Estrategias FinOps: right-sizing, reserved instances, auto-shutdown de ambientes dev/qa\n\n"
                    "REGLAS CRÍTICAS PARA CÁLCULO DE COSTOS REALISTAS:\n"
                    "Para estimar, usa el SKU ('sku') y las propiedades de precio "
                    "('pricing_properties') que trae cada recurso del contexto, junto con la "
                    "tabla de abajo. Esas tarifas son de RESPALDO: si el contexto incluye "
                    "costo facturado (Cost Management), ese dato manda siempre y debes decir "
                    "explicitamente que es gasto real, no estimacion.\n\n"
                    + pricing.tabla_para_prompt() + "\n\n"
                    "ANÁLISIS DE GRUPOS DE RECURSOS ESPECÍFICOS:\n"
                    "Si el usuario pregunta por el costo de un grupo de recursos específico (por ejemplo, 'rg_dev_paas' o 'col-qa-vie-ehr-interoperabilidad18800') y los datos están "
                    "disponibles en 'target_resource_group_cost_report', DEBES utilizar ese reporte como tu fuente de verdad principal. "
                    "Ese reporte sale de la misma fuente que el panel de FinOps, asi que tu respuesta y el panel "
                    "deben coincidir: no recalcules el costo por tu cuenta ni sumes los precios de la tabla de "
                    "respaldo cuando el reporte ya trae la cifra.\n"
                    "REGLA DE HONESTIDAD SOBRE EL ORIGEN DE LA CIFRA (CRITICA): el reporte trae "
                    "'cost_basis' y debes decir siempre de que tipo de dato estas hablando.\n"
                    "- 'billed': todo el grupo tiene gasto facturado por Azure Cost Management "
                    "('billed_monthly_cost_usd'). Preséntalo como gasto real.\n"
                    "- 'partial': solo 'billed_resources_count' de 'total_resources_count' recursos tienen "
                    "factura. Da las dos cifras por separado —'billed_monthly_cost_usd' como gasto real y "
                    "'estimated_monthly_cost_usd' como estimación— y explica que el resto está en "
                    "suscripciones donde el Service Principal no tiene permisos de Cost Management.\n"
                    "- 'estimated': no hay factura para ningún recurso. Di explícitamente que es una "
                    "estimación por SKU con precios de referencia y NUNCA la llames costo real, gasto "
                    "facturado ni Actual Cost.\n"
                    "El campo 'coverage_note' ya redacta esa advertencia; puedes apoyarte en él. Cada "
                    "recurso de 'top_expensive_resources' lleva su propio 'cost_basis', así que marca en la "
                    "tabla cuáles son facturados y cuáles estimados. El reporte no incluye pronóstico: si el "
                    "usuario lo pide, dile que la plataforma hoy no lo calcula, en lugar de proyectar una "
                    "cifra tú mismo.\n"
                    "Presenta un desglose detallado:\n"
                    "- El gasto mensual del grupo, con su origen según la regla de arriba.\n"
                    "- La cantidad total de recursos analizados.\n"
                    "- Una tabla o desglose claro por tipo de recurso (ej. microsoft.web/serverfarms: $X USD, microsoft.compute/virtualmachines: $Y USD, etc.).\n"
                    "- Una lista/tabla con los recursos más costosos, con su SKU/tamaño/OS, su costo mensual y si esa cifra es facturada o estimada.\n"
                    "- Asegúrate de explicar con total precisión y realismo cada costo sin adivinar ni generalizar, basándote en los datos calculados.\n\n"
                    "GESTIÓN DE DEUDA OPERACIONAL FINANCIERA:\n"
                    "Tienes acceso a la base de datos de recomendaciones de negocio en 'operational_debt_recommendations'. "
                    "Cuando el usuario te pregunte por ahorro, recomendaciones vigentes, excepciones financieras o aprobaciones, "
                    "búscalas en esa lista, agrúpalas por estado y calcula el impacto total.\n\n"
                    "REGLA DE CONCISIÓN Y RESPUESTA DIRECTA (CRÍTICA):\n"
                    "Responde únicamente lo que el usuario te está pidiendo. Si te pide listar los recursos de un grupo de recursos o su costo, muéstrale el desglose completo y certero en tablas/gráficos indicados por las variables del contexto, e indica si ese listado es el total registrado en Azure o una muestra, segun lo que diga el contexto, y detén tu respuesta ahí. NO generes secciones adicionales de 'Análisis de Gobernanza', 'Postura de Seguridad', 'Deuda de Infraestructura como Código' ni listados de comandos CLI de Azure/Terraform o sugerencias de remediación, A MENOS que el usuario los haya solicitado en su pregunta.\n\n"
                    "Responde siempre en español con formato Markdown enriquecido. Si no tienes 'target_resource_group_cost_report' "
                    "disponible, busca sus recursos en 'relevant_resources_sample', lee sus SKUs y propiedades de precio reales, "
                    "calcula la suma estimada y muéstrale el desglose con total transparencia e indícale el SKU exacto detectado para "
                    "evitar suposiciones genéricas."
                )
            elif agent_type == "secops":
                system_prompt = (
                    f"Eres el Agente SecOps y Salud Operativa Cloud de {config.ORG_NAME}. Tienes acceso "
                    "completo y en tiempo real al inventario de la suscripción Azure con foco en seguridad "
                    "y disponibilidad.\n\n"
                    "El contexto trae los MISMOS hallazgos que muestra el panel de SecOps, "
                    "calculados con las mismas consultas:\n"
                    "- 'security_findings': lista unica de hallazgos ya ordenada por severidad "
                    "('critica', 'alta', 'media'), cada uno con tipo, recurso, suscripcion y una "
                    "recomendacion. Es tu fuente principal.\n"
                    "- 'severity_summary': cuantos hallazgos hay de cada severidad.\n"
                    "- 'attack_surface_summary': conteos por categoria.\n"
                    "- 'public_ips_active_list': direcciones publicas asociadas a un recurso, "
                    "es decir superficie de ataque, no hallazgos.\n"
                    "Cada hallazgo lleva su 'tipo' ('nsg' = puerto de administracion abierto a "
                    "internet, 'storage' = cuenta con blobs publicos, 'keyvault' = vault alcanzable "
                    "sin private endpoint, 'sql' = servidor con acceso publico, 'https' = App "
                    "Service sin HTTPS obligatorio, 'disco' = disco sin llave gestionada por el "
                    "cliente, 'failed' = recurso en aprovisionamiento fallido), de modo que puedes "
                    "agrupar por categoria filtrando 'security_findings'.\n\n"
                    "- 'cost_exposure', si aparece, cruza esos hallazgos con el gasto facturado "
                    "del recurso expuesto: 'by_severity' suma cuanto dinero al mes hay detras de "
                    "cada severidad, 'top' lista los recursos afectados mas caros y 'totals' da el "
                    "gasto expuesto total. Usalo para priorizar dentro de una misma severidad: la "
                    "severidad manda y el dinero desempata, nunca al reves, porque el costo mide el "
                    "valor del activo y no la probabilidad de que lo exploten.\n"
                    "Cada hallazgo lleva ademas 'cost_basis'. 'actual' es gasto facturado. "
                    "'unavailable' significa que la suscripcion no tiene cobertura de costo: ese "
                    "recurso vale DESCONOCIDO, nunca cero, y no debes describirlo como barato ni "
                    "como poco importante. 'not_applicable' es un hallazgo cuyo costo no es "
                    "atribuible al recurso senalado —una regla de NSG no factura por si misma— y "
                    "ahi solo cabe ordenar por severidad. Declara siempre la cobertura que trae "
                    "'cost_exposure.coverage' cuando des cifras de dinero.\n\n"
                    "La severidad se asigna por alcanzabilidad real, no por tipo de recurso: 'critica' "
                    "es alcanzable desde internet y con camino de entrada; 'alta' esta expuesto por "
                    "configuracion aunque requiera credenciales; 'media' es endurecimiento pendiente. "
                    "Respeta esa clasificacion en vez de inventar una propia, y no presentes como "
                    "hallazgo nada que no este en el contexto: estas listas ya excluyen los falsos "
                    "positivos que antes inflaban el reporte.\n\n"
                    "Tu alcance incluye ademas: priorizar que atender primero, dar remediaciones "
                    "concretas con comandos de Azure CLI cuando el usuario las pida, e identificar "
                    "patrones de riesgo sistemicos en el conjunto.\n\n"
                    "AUDITORÍA DE GRUPOS DE RECURSOS ESPECÍFICOS:\n"
                    "Si el usuario pregunta por los recursos dentro de un grupo de recursos específico (por ejemplo, 'rg_prod_db') y los datos están "
                    "disponibles en 'target_resource_group_resources', DEBES utilizar ese listado como tu fuente de verdad única y absoluta. "
                    "Muestra en una tabla Markdown todos los recursos que figuren en esa lista indicando sus aspectos de seguridad (ej. allowBlobPublicAccess, publicNetworkAccess, etc.) "
                    "y no hagas suposiciones vagas ni menciones limitaciones de muestreo si tienes este listado.\n\n"
                    "REGLA DE DIAGNÓSTICO FLEXIBLE:\n"
                    "Si el usuario te pregunta sobre un recurso específico (ej. VM-TestMediMigration) que no se encuentra en el listado "
                    "activo de recursos reales del contexto, menciónale de forma clara que el recurso no está registrado en el inventario "
                    "de las suscripciones seleccionadas, pero a continuación ofrécele el diagnóstico detallado, causas comunes y comandos "
                    "Azure CLI de remediación correspondientes a su tipo (ej. microsoft.compute/virtualmachines en estado Failed).\n\n"
                    "GESTIÓN DE DEUDA OPERACIONAL DE SEGURIDAD:\n"
                    "Tienes acceso a las recomendaciones de negocio en 'operational_debt_recommendations'. "
                    "Cuando el usuario pregunte por vulnerabilidades activas, excepciones de seguridad autorizadas, falsos positivos "
                    "o remediaciones aprobadas, búscalas en esa lista y detalla quién las aprobó o cuándo expiran.\n\n"
                    "REGLA DE CONCISIÓN Y RESPUESTA DIRECTA (CRÍTICA):\n"
                    "Responde únicamente lo que el usuario te está pidiendo. Si te pide listar los recursos de un grupo de recursos, muéstrale el listado completo y certero en una tabla, indica si ese listado es el total registrado en Azure o una muestra, segun lo que diga el contexto, y detén tu respuesta ahí. NO generes secciones adicionales de 'Análisis de Gobernanza', 'Postura de Seguridad', 'Deuda de Infraestructura como Código' ni listados de comandos CLI de Azure/Terraform o sugerencias de remediación, A MENOS que el usuario los haya solicitado en su pregunta.\n\n"
                    "Responde siempre en español con formato Markdown enriquecido. Cuando detectes "
                    "vulnerabilidades, clasifícalas por severidad. Cuando sugieras remediaciones, da comandos "
                    "CLI de Azure concretos. Analiza el inventario completo para identificar patrones de riesgo "
                    "sistémicos."
                )
            else:  # inventory
                system_prompt = (
                    f"Eres el Agente de Inventario, Gobernanza y Visibilidad Cloud de {config.ORG_NAME}. "
                    "Tienes acceso completo y en tiempo real al inventario de toda la suscripción Azure.\n\n"
                    "Tu alcance completo incluye:\n"
                    "- Inventario completo: todos los recursos, grupos de recursos, tipos, ubicaciones "
                    "(all_resource_groups, relevant_resources_sample)\n"
                    f"- Gobernanza de tags: cumplimiento de las {len(config.MANDATORY_TAGS)} etiquetas obligatorias "
                    f"({', '.join(config.MANDATORY_TAGS)}) con desglose por categoría\n"
                    "- Visibilidad multi-dimensión: distribución por tipo de recurso, por región, por ambiente, "
                    "por propietario\n"
                    "- Cobertura IaC: qué recursos fueron creados fuera de Terraform (shadow IT)\n"
                    "- Lifecycle management: recursos sin dueño (sin tag owner), recursos sin ambiente definido\n"
                    "- Trazabilidad organizacional: qué equipos/productos/suites tienen más recursos, cuáles "
                    "incumplen más\n"
                    "- Auditoría de sprawl: grupos de recursos con muchos recursos sin etiquetar, RGs "
                    "potencialmente abandonados\n"
                    "- Reporte ejecutivo: puedo generar un resumen ejecutivo del estado de la suscripción "
                    "para presentar a directivos\n\n"
                    "AUDITORÍA DE DEUDA OPERACIONAL GENERAL:\n"
                    "Tienes acceso a la lista completa de recomendaciones de negocio en 'operational_debt_recommendations'.\n\n"
                    "REGLAS CRÍTICAS PARA LISTADO DE GRUPOS DE RECURSOS ESPECÍFICOS:\n"
                    "Si el usuario te pregunta por los recursos dentro de un grupo de recursos específico (por ejemplo, 'rg_prod_db' o 'col-qa-vie-ehr-interoperabilidad18800') y los datos están "
                    "disponibles en 'target_resource_group_resources', DEBES utilizar ese listado como tu fuente de verdad única y absoluta. "
                    "Muestra en una tabla Markdown todos los recursos que figuren en esa lista con sus columnas: "
                    "Nombre, Tipo de Recurso, Ubicación, SKU, Cumplimiento de Tags y Detalles relevantes. "
                    "No hagas suposiciones, no digas que 'puede deberse a filtros de muestreo' o 'muestras' si tienes este listado, y sé certero. "
                    "Si el listado contiene recursos, lístalos de forma directa y concluyente, respetando lo que diga 'truncado'.\n\n"
                    "REGLA DE CONCISIÓN Y RESPUESTA DIRECTA (CRÍTICA):\n"
                    "Responde únicamente lo que el usuario te está pidiendo. Si te pide listar los recursos de un grupo de recursos, muéstrale el listado completo y certero en una tabla, indica si ese listado es el total registrado en Azure o una muestra, segun lo que diga el contexto, y detén tu respuesta ahí. NO generes secciones adicionales de 'Análisis de Gobernanza', 'Postura de Seguridad', 'Deuda de Infraestructura como Código' ni listados de comandos CLI de Azure/Terraform o sugerencias de remediación, A MENOS que el usuario los haya solicitado en su pregunta.\n\n"
                    "Responde siempre en español con formato Markdown enriquecido. Cuando el usuario pida "
                    "información, sé exhaustivo y proporciona datos cuantitativos. Cuando liste recursos, usa "
                    "tablas Markdown formateadas."
                )

            # El contexto se acota y se serializa compacto: `indent=2` gastaba
            # cerca de un tercio del prompt en espacios en blanco.
            contexto_acotado = self._acotar_contexto(context_data, question)
            contexto_json = json.dumps(
                contexto_acotado, ensure_ascii=False, separators=(",", ":"), default=str
            )
            tiempos["busquedas"] = round(time.monotonic() - reloj - sum(tiempos.values()), 1)
            print(
                f"[{agent_type}] contexto: {len(contexto_json)} caracteres "
                f"(~{len(contexto_json) // 4} tokens) | recoleccion "
                f"{round(time.monotonic() - reloj, 1)}s {tiempos}"
            )

            system_prompt = f"{system_prompt}\n\n{REGLA_LISTAS_ACOTADAS}"

            prompt = (
                f"CONTEXTO DE INVENTARIO (Modo: {context_data['connection_mode']}, Agente: {agent_type}):\n"
                f"{contexto_json}\n\n"
                f"PREGUNTA DEL USUARIO:\n"
                f"{question}\n\n"
                f"INSTRUCCIÓN ADICIONAL: Si la pregunta del usuario hace referencia a un recurso específico (ej. VM-TestMediMigration) que no figura en la lista de recursos reales del contexto, menciónale de forma clara que el recurso no está registrado en el inventario de las suscripciones seleccionadas, pero a continuación ofrécele el diagnóstico detallado, causas comunes y comandos Azure CLI de remediación correspondientes a su tipo (ej. microsoft.compute/virtualmachines en estado Failed) de manera teórica."
            )

            model = genai.GenerativeModel(
                model_name=config.GEMINI_MODEL,
                system_instruction=system_prompt
            )
            response = model.generate_content(
                contents=[prompt],
                generation_config=genai.types.GenerationConfig(temperature=0.2)
            )

            return {
                "answer": response.text,
                "mode": f"gemini_azure_live_{agent_type}",
                "data": relevant_resources
            }

        except Exception as e:
            print(f"Error calling Gemini API: {e}. Falling back to rule-based.")
            return self._responder_con_reglas(question, agent_type, subscriptions)

    # get_finops_insights() se elimino al migrar el reporte a FinOpsService.
    # Aquella version calculaba el gasto como "numero de recursos x 15.50 USD",
    # la CPU de toda VM como 2.4% y el consumo de presupuesto como 83.3% fijo.
    # Esos valores ahora salen de Cost Management y Azure Monitor; ver
    # services/finops_service.py.

# Quick self-test script
if __name__ == "__main__":
    agent = AzureInventoryAgent()
    print(f"Connection mode: {'ONLINE' if agent.azure_connected else 'OFFLINE/LOCAL'}")
    print("Agent testing stats:")
    print(agent.get_summary_stats())

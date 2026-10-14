"""
Agente conversacional de inventario, costos y seguridad.

La clase coordina la conversación (`ask`) y comparte con el panel sus servicios;
el resto vive en módulos que reciben el agente:

* contexto.py      datos del dominio para el modelo y su presupuesto.
* prompts.py       instrucciones de sistema de cada agente.
* estadisticas.py  KPIs en vivo, búsqueda y costo de un grupo (también para el bot y los routers heredados).
* rule_answers.py  respuestas sin modelo de lenguaje.

Los métodos de la clase con esos nombres son delegados: los llamadores no cambian.
"""

import re
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional
from app import llm
from app.core import config
from app.providers.azure import AzureClient
from app.agents import contexto, estadisticas, prompts, rule_answers
from app.services import pricing

# El .env lo carga app.core.config (respeta CLOUDOPS_SKIP_DOTENV).

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


    def get_summary_stats(self, *args, **kwargs):
        return estadisticas.resumen_en_vivo(self, *args, **kwargs)

    def get_subscription_name(self, *args, **kwargs):
        return estadisticas.nombre_de_suscripcion(self, *args, **kwargs)

    def search_resources(self, *args, **kwargs):
        return estadisticas.buscar_recursos(self, *args, **kwargs)

    def estimate_resource_cost(self, r: Dict[str, Any]) -> float:
        """
        Estimacion mensual de un recurso por tipo y SKU.

        La tabla de tarifas vive en services/pricing.py, que es tambien la que
        alimenta el respaldo de FinOps y el prompt del agente: antes existian
        tres copias y ya diferian entre si.
        """
        return pricing.costo_mensual_estimado(r)

    def generate_rg_cost_report(self, *args, **kwargs):
        return estadisticas.reporte_de_costo_de_grupo(self, *args, **kwargs)

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

    def ask_rule_based(self, *args, **kwargs):
        return rule_answers.respuesta_general(self, *args, **kwargs)

    _tags_como_dict = staticmethod(contexto.tags_como_dict)

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

    _acotar = staticmethod(contexto.acotar)

    def _acotar_contexto(self, *args, **kwargs):
        return contexto.acotar_contexto(self, *args, **kwargs)

    # Presupuesto total que la recoleccion de contexto puede gastar esperando a
    # Azure. Antes cada consulta tenia su propio `timeout=8`, resueltos en serie:
    # trece consultas podian sumar mas de cien segundos, peligrosamente cerca del
    # corte de 230s del gateway de App Service. El limite ahora es del conjunto.
    PRESUPUESTO_CONTEXTO_SEGUNDOS = 25.0

    # Limite total de las nueve consultas que producen los KPIs del panel.
    PRESUPUESTO_KPIS_SEGUNDOS = 15.0

    def _contexto_de_dominio(self, *args, **kwargs):
        return contexto.contexto_de_dominio(self, *args, **kwargs)

    def _ejecutar_en_paralelo(self, *args, **kwargs):
        return contexto.ejecutar_en_paralelo(self, *args, **kwargs)

    def ask(self, question: str, agent_type: str = "inventory", subscriptions: Optional[List[str]] = None,
            usuario: Optional[str] = None) -> Dict[str, Any]:
        """Responde con el modelo de lenguaje y el contexto real; sin modelo, con el motor de reglas."""
        if not llm.disponible():
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

            # 7. Instrucciones de sistema del agente (app/agents/prompts.py)
            system_prompt = prompts.prompt_de_sistema(agent_type)

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

            respuesta = llm.generar(f"chat.{agent_type}", system_prompt, prompt, temperatura=0.2, usuario=usuario)

            return {
                "answer": respuesta.texto,
                "mode": f"llm_{llm.proveedor().nombre}_{agent_type}",
                "data": relevant_resources
            }

        except Exception as e:
            print(f"El modelo no respondió ({e}); se responde con el motor de reglas.")
            return self._responder_con_reglas(question, agent_type, subscriptions)

    # get_finops_insights() se elimino al migrar el reporte a FinOpsService.
    # Aquella version calculaba el gasto como "numero de recursos x 15.50 USD",
    # la CPU de toda VM como 2.4% y el consumo de presupuesto como 83.3% fijo.
    # Esos valores ahora salen de Cost Management y Azure Monitor; ver
    # services/finops_service.py.

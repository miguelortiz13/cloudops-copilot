import os
import time
import logging
import threading
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor

from app.core import config
from app.services import governance
from app.services import cost_service as cost_module

logger = logging.getLogger("inventory_service")

# Constants
# Esquema configurable; ver app/core/config.py y docs/governance/tagging-policy.md.
MANDATORY_TAGS = config.MANDATORY_TAGS
INVALID_TAG_VALUES = {"", "n/a", "na", "por confirmar", "tbd", "sin definir", "none", "null"}
PRODUCTION_ENVIRONMENTS = {"prod", "production", "prd", "produccion", "producción"}
NON_PRODUCTION_ENVIRONMENTS = {"dev", "development", "qa", "staging", "test", "sandbox", "demo", "uat"}

class InventoryService:
    """Inventario normalizado sobre Resource Graph (via AzureClient)."""
    
    def __init__(self, azure):
        self.azure = azure
        self._cache = {}
        self._cache_ttl = int(os.getenv("INVENTORY_CACHE_TTL_SECONDS", "300"))
        self._lock = threading.Lock()
        self._subscription_cache = {}
        self._sub_cache_time = 0
    
    # --- Subscriptions ---
    
    def list_accessible_subscriptions(self) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Lists all subscriptions accessible to the Service Principal.
        Returns (subscriptions_list, warnings_list).
        """
        warnings = []
        if not self.azure.azure_connected:
            return [], ["Azure no está conectado. Verifica las credenciales del Service Principal."]
        
        now = time.time()
        if self._subscription_cache and (now - self._sub_cache_time < self._cache_ttl):
            return self._subscription_cache.get("data", []), []
        
        try:
            kql = (
                "resourcecontainers "
                "| where type == 'microsoft.resources/subscriptions' "
                "| project subscriptionId, displayName=name, state=properties.state, tenantId"
            )
            results = self.azure.query_azure_resource_graph(kql, bypass_cache=True, subscriptions=[])
            
            subs = []
            for r in results:
                subs.append({
                    "subscriptionId": r.get("subscriptionId", ""),
                    "displayName": r.get("displayName", r.get("name", "")),
                    "state": str(r.get("state", "Enabled")),
                    "tenantId": r.get("tenantId", os.getenv("AZURE_TENANT_ID", ""))
                })
            
            # Filter by allowed subscriptions if configured
            allowed = os.getenv("AZURE_ALLOWED_SUBSCRIPTIONS", "").strip()
            if allowed:
                allowed_ids = {s.strip().lower() for s in allowed.split(",") if s.strip()}
                subs = [s for s in subs if s["subscriptionId"].lower() in allowed_ids]
                if not subs:
                    warnings.append("AZURE_ALLOWED_SUBSCRIPTIONS está configurado pero ninguna suscripción coincide.")
            
            self._subscription_cache = {"data": subs}
            self._sub_cache_time = now
            
            if not subs:
                warnings.append("El Service Principal no tiene acceso a ninguna suscripción.")
            
            logger.info(f"Listed {len(subs)} accessible subscriptions")
            return subs, warnings
            
        except Exception as e:
            logger.error(f"Error listing subscriptions: {e}")
            return [], [f"Error al listar suscripciones: {str(e)}"]
    
    # --- Tag Evaluation ---
    
    @staticmethod
    def evaluate_mandatory_tags(tags: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluates compliance of mandatory tags."""
        if not tags:
            tags = {}
        
        tags_lower = {k.lower(): v for k, v in tags.items() if v is not None}
        present = []
        missing = []
        
        for tag in MANDATORY_TAGS:
            tag_key = tag.lower()
            val = tags_lower.get(tag_key)
            if val is not None and str(val).strip().lower() not in INVALID_TAG_VALUES:
                present.append(tag)
            else:
                missing.append(tag)
        
        total_required = len(MANDATORY_TAGS)
        present_count = len(present)
        compliance = round((present_count / total_required) * 100, 1) if total_required > 0 else 0.0
        
        return {
            "totalRequired": total_required,
            "present": present_count,
            "missing": missing,
            "compliancePercentage": compliance,
            "isCompliant": present_count == total_required
        }
    
    # --- Shadow IT Classification ---
    
    @staticmethod
    def classify_shadow_it(
        tags: Dict[str, Any],
        managed_by: Optional[str],
        tag_result: Dict[str, Any],
        resource_group: str = "",
        resource_type: str = "",
        resource_id: str = "",
        managed_ids: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        """
        Clasifica un recurso como candidato a Shadow IT.

        La regla y su motivo viven en services/governance.py, que es la unica
        definicion de la plataforma. Aqui se exige que fallen las cuatro
        senales: sin evidencia de IaC, no derivado de otro recurso de Azure, sin
        custodio identificable y con tags obligatorias incompletas. La version
        anterior bastaba con que faltara la tag de IaC y el campo `managedBy`,
        que Azure solo pone en recursos hijos, y por eso marcaba el 90% del
        inventario.
        """
        if not tags:
            tags = {}

        tags_lower = {k.lower(): str(v).lower() for k, v in tags.items() if v is not None}

        # Dos evidencias de IaC: la tag, que solo dice que alguien etiqueto, y el
        # estado de Terraform, que lo demuestra. La segunda solo exonera.
        en_estado = governance.esta_en_estado(resource_id, managed_ids)
        tiene_iac = en_estado or governance.tiene_evidencia_iac(tags_lower)
        derivado = governance.es_derivado(managed_by, resource_group, resource_type)
        tiene_custodio = governance.tiene_custodio(tags_lower, INVALID_TAG_VALUES)
        conforme = tag_result.get("isCompliant", False)

        is_candidate = not tiene_iac and not derivado and not tiene_custodio and not conforme

        reasons = []
        if is_candidate:
            faltan = tag_result.get("missing") or []
            reasons.append("Sin marca de IaC en las tags")
            reasons.append("sin custodio identificable")
            reasons.append(
                f"faltan {len(faltan)} de {tag_result.get('totalRequired', 0)} tags obligatorias"
            )

        # Puntaje de completitud de los datos de gobernanza del recurso.
        completeness_score = 0.0
        if tags:
            completeness_score += 30
        if conforme:
            completeness_score += 30
        if tiene_iac:
            completeness_score += 20
        if str(managed_by or "").strip():
            completeness_score += 10
        if tiene_custodio:
            completeness_score += 10

        return {
            "isShadowItCandidate": is_candidate,
            "shadowItReason": "; ".join(reasons) if reasons else None,
            "dataCompletenessScore": min(completeness_score, 100.0),
            "hasIacEvidence": tiene_iac,
            "isDerived": derivado,
            # 'estado' es evidencia probada; 'tags' solo declarada.
            "iacEvidenceSource": "estado" if en_estado else ("tags" if tiene_iac else None),
        }

    # --- Governance Info ---
    
    @staticmethod
    def build_governance_info(tags: Dict[str, Any], managed_by: Optional[str], tag_result: Dict[str, Any], shadow_it: Dict[str, Any]) -> Dict[str, Any]:
        """Builds governance metadata for a resource."""
        if not tags:
            tags = {}
        tags_lower = {k.lower(): str(v).strip() for k, v in tags.items() if v is not None}
        
        owner_keys = governance.OWNER_TAG_KEYS
        owner_candidate = None
        for k in owner_keys:
            if k in tags_lower and tags_lower[k].lower() not in INVALID_TAG_VALUES:
                owner_candidate = tags_lower[k]
                break
        
        env_val = tags_lower.get("environment", "").lower()
        is_prod = env_val in PRODUCTION_ENVIRONMENTS
        is_non_prod = env_val in NON_PRODUCTION_ENVIRONMENTS
        
        return {
            "hasOwnerCandidate": owner_candidate is not None,
            "ownerCandidate": owner_candidate,
            "isProduction": is_prod,
            "isNonProduction": is_non_prod,
            "isShadowItCandidate": shadow_it.get("isShadowItCandidate", False),
            "shadowItReason": shadow_it.get("shadowItReason"),
            "dataCompletenessScore": shadow_it.get("dataCompletenessScore", 0.0),
            "hasIacEvidence": shadow_it.get("hasIacEvidence", False),
            "iacEvidenceSource": shadow_it.get("iacEvidenceSource"),
            "isDerived": shadow_it.get("isDerived", False)
        }
    
    # --- Resource Normalization ---
    
    def normalize_resource(self, raw: Dict[str, Any], sub_name_map: Dict[str, str]) -> Dict[str, Any]:
        """Normalizes a raw ARG resource into a structured inventory item."""
        tags = raw.get("tags") or {}
        tags_clean = {k: str(v) for k, v in tags.items() if v is not None}
        tags_lower = {k.lower(): str(v).strip() for k, v in tags_clean.items()}
        
        sku = raw.get("sku") or {}
        sub_id = raw.get("subscriptionId", "")
        res_type = raw.get("type", "")
        
        tag_result = self.evaluate_mandatory_tags(tags_clean)
        shadow_it = self.classify_shadow_it(
            tags_clean, raw.get("managedBy"), tag_result,
            raw.get("resourceGroup", ""), raw.get("type", ""),
            raw.get("id", ""), self._managed_ids()
        )
        governance = self.build_governance_info(tags_clean, raw.get("managedBy"), tag_result, shadow_it)
        
        # Type display name
        type_parts = res_type.split("/")
        type_display = type_parts[-1] if type_parts else res_type
        
        return {
            "id": raw.get("id", ""),
            "name": raw.get("name", ""),
            "type": res_type,
            "typeDisplayName": type_display,
            "subscriptionId": sub_id,
            "subscriptionName": sub_name_map.get(sub_id, sub_id),
            "resourceGroup": raw.get("resourceGroup", ""),
            "location": raw.get("location", ""),
            "kind": raw.get("kind"),
            "skuName": sku.get("name") if isinstance(sku, dict) else None,
            "skuTier": sku.get("tier") if isinstance(sku, dict) else None,
            "provisioningState": raw.get("provisioningState") or None,
            "createdTime": raw.get("createdTime") or None,
            "changedTime": raw.get("changedTime") or None,
            "managedBy": raw.get("managedBy"),
            "tags": tags_clean,
            "environment": tags_lower.get("environment"),
            # Valor de cada tag obligatoria del esquema configurado.
            "tagValues": {t: tags_lower.get(t.lower()) for t in MANDATORY_TAGS},
            "mandatoryTags": tag_result,
            "governance": governance
        }
    
    # --- Cache Helpers ---
    
    def _resolve_scope(self, subscription_ids: List[str]) -> List[str]:
        """
        Resuelve el conjunto de suscripciones a consultar.

        Una lista vacia significa "todas las accesibles", pero no puede pasarse
        tal cual a Resource Graph: `list_accessible_subscriptions` es quien
        aplica el filtro de AZURE_ALLOWED_SUBSCRIPTIONS. Delegar la resolucion en
        Azure saltaria ese filtro y el panel mostraria suscripciones que la
        configuracion excluye explicitamente.

        Todos los caminos —agregados, paginacion y descarga completa— deben pasar
        por aqui para que el alcance sea el mismo en los tres.
        """
        if subscription_ids:
            return [s for s in subscription_ids if s]
        subs, _ = self.list_accessible_subscriptions()
        return [s["subscriptionId"] for s in subs]

    def _cache_key(self, prefix: str, sub_ids: List[str], extra: str = "") -> str:
        key_data = f"{prefix}:{','.join(sorted(sub_ids))}:{extra}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def _get_cached(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._cache:
                ts, data = self._cache[key]
                if time.time() - ts < self._cache_ttl:
                    return data
                del self._cache[key]
        return None
    
    def _set_cached(self, key: str, data: Any):
        with self._lock:
            self._cache[key] = (time.time(), data)
    
    # --- Subscription Name Map ---
    
    def _get_subscription_name_map(self, sub_ids: List[str]) -> Dict[str, str]:
        """Returns a dict mapping subscription IDs to display names."""
        subs, _ = self.list_accessible_subscriptions()
        return {s["subscriptionId"]: s["displayName"] for s in subs}
    
    # --- Core Query ---
    
    def _fetch_all_resources(self, subscription_ids: List[str], force_refresh: bool = False) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Fetches all resources from ARG for the given subscriptions.
        Returns (normalized_resources, warnings).
        """
        warnings = []
        if not self.azure.azure_connected:
            return [], ["Azure no está conectado."]
        
        if not subscription_ids:
            subs, w = self.list_accessible_subscriptions()
            warnings.extend(w)
            subscription_ids = [s["subscriptionId"] for s in subs]
        # Nota: equivale a _resolve_scope, pero aqui ademas se propagan los
        # avisos de la enumeracion para incluirlos en la respuesta.
        
        if not subscription_ids:
            return [], warnings + ["No hay suscripciones disponibles para consultar."]
        
        cache_key = self._cache_key("resources", subscription_ids)
        if not force_refresh:
            cached = self._get_cached(cache_key)
            if cached is not None:
                logger.info(f"Cache hit for {len(subscription_ids)} subscriptions")
                return cached, []
        
        start_time = time.time()
        sub_name_map = self._get_subscription_name_map(subscription_ids)
        
        # Se extraen los tres campos que interesan de `properties` y se descarta el
        # resto del bag antes de proyectar. Traerlo completo movia ~2.6 MB por
        # suscripcion para leer tres cadenas: proyectar solo lo necesario reduce
        # la transferencia cerca de un 86% y la consulta pasa de ~11s a ~3s.
        kql = (
            "resources "
            "| extend provisioningState = tostring(properties.provisioningState) "
            "| extend createdTime = tostring(properties.createdTime) "
            "| extend changedTime = tostring(properties.changedTime) "
            "| project id, name, type, kind, subscriptionId, resourceGroup, location, "
            "  tags, managedBy, sku, provisioningState, createdTime, changedTime"
        )
        
        try:
            raw_results = self.azure.query_azure_resource_graph(
                kql, bypass_cache=force_refresh, subscriptions=subscription_ids
            )
        except Exception as e:
            error_msg = str(e)
            logger.error(f"ARG query error: {error_msg}")
            if "403" in error_msg or "AuthorizationFailed" in error_msg:
                warnings.append(f"Acceso denegado a una o más suscripciones: {error_msg[:200]}")
            elif "429" in error_msg or "throttl" in error_msg.lower():
                warnings.append("Throttling detectado en Azure Resource Graph. Intenta de nuevo en unos minutos.")
            else:
                warnings.append(f"Error consultando Azure Resource Graph: {error_msg[:200]}")
            return [], warnings
        
        normalized = []
        for raw in raw_results:
            try:
                item = self.normalize_resource(raw, sub_name_map)
                normalized.append(item)
            except Exception as e:
                logger.warning(f"Error normalizing resource {raw.get('name', 'unknown')}: {e}")
        
        elapsed = round(time.time() - start_time, 2)
        logger.info(f"Fetched and normalized {len(normalized)} resources from {len(subscription_ids)} subscriptions in {elapsed}s")
        
        self._set_cached(cache_key, normalized)
        return normalized, warnings
    
    # --- Filtering ---
    
    @staticmethod
    def apply_filters(resources: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Applies filters to normalized resources."""
        result = resources
        
        search = (filters.get("search") or "").strip().lower()
        if search:
            result = [r for r in result if (
                search in r.get("name", "").lower() or
                search in r.get("type", "").lower() or
                search in r.get("resourceGroup", "").lower() or
                search in r.get("id", "").lower() or
                search in r.get("subscriptionName", "").lower()
            )]
        
        rg_filter = filters.get("resourceGroups", [])
        if rg_filter:
            rg_lower = {rg.lower() for rg in rg_filter}
            result = [r for r in result if r.get("resourceGroup", "").lower() in rg_lower]
        
        type_filter = filters.get("types", [])
        if type_filter:
            type_lower = {t.lower() for t in type_filter}
            result = [r for r in result if r.get("type", "").lower() in type_lower]
        
        loc_filter = filters.get("locations", [])
        if loc_filter:
            loc_lower = {l.lower() for l in loc_filter}
            result = [r for r in result if r.get("location", "").lower() in loc_lower]
        
        env_filter = filters.get("environments", [])
        if env_filter:
            env_lower = {e.lower() for e in env_filter}
            result = [r for r in result if (r.get("environment") or "").lower() in env_lower]
        
        missing_tags = filters.get("missingTags", [])
        if missing_tags:
            missing_lower = {t.lower() for t in missing_tags}
            result = [r for r in result if any(
                t.lower() in missing_lower for t in r.get("mandatoryTags", {}).get("missing", [])
            )]
        
        if filters.get("onlyNonCompliant"):
            result = [r for r in result if not r.get("mandatoryTags", {}).get("isCompliant", True)]
        
        if filters.get("onlyShadowItCandidates"):
            result = [r for r in result if r.get("governance", {}).get("isShadowItCandidate", False)]
        
        return result
    
    # --- Public API Methods ---
    
    @staticmethod
    def _kql_literal(value: str) -> str:
        """Escapa un valor para incrustarlo en una cadena KQL."""
        return str(value).replace("\\", "\\\\").replace("'", "\\'")

    def _kql_filter_clauses(
        self, filters: Dict[str, Any], sub_name_map: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Traduce los filtros de la interfaz a clausulas KQL.

        Filtrar en Azure en vez de en memoria es lo que permite no descargar el
        inventario completo para mostrar una pagina de cincuenta filas.
        """
        clauses: List[str] = []

        search = (filters.get("search") or "").strip().lower()
        if search:
            term = self._kql_literal(search)
            campos = (
                "tolower(name) contains '{t}' or tolower(type) contains '{t}' "
                "or tolower(resourceGroup) contains '{t}' or tolower(id) contains '{t}'"
            ).format(t=term)

            # El filtrado en memoria tambien busca en el nombre de la
            # suscripcion, que Resource Graph no expone como columna. Se traduce
            # resolviendo aqui que suscripciones coinciden por nombre e
            # incluyendo sus recursos, para no cambiar lo que el usuario ve.
            matching_subs = [
                sub_id for sub_id, nombre in (sub_name_map or {}).items()
                if search in str(nombre).lower()
            ]
            if matching_subs:
                joined = ", ".join(f"'{self._kql_literal(x)}'" for x in matching_subs)
                campos += f" or subscriptionId in~ ({joined})"

            clauses.append(f"| where {campos}")

        def in_clause(field: str, values: List[str]) -> Optional[str]:
            if not values:
                return None
            joined = ", ".join(f"'{self._kql_literal(str(v).lower())}'" for v in values)
            return f"| where tolower({field}) in ({joined})"

        for field, key in (
            ("resourceGroup", "resourceGroups"),
            ("type", "types"),
            ("location", "locations"),
        ):
            clause = in_clause(field, filters.get(key) or [])
            if clause:
                clauses.append(clause)

        environments = filters.get("environments") or []
        if environments:
            joined = ", ".join(f"'{self._kql_literal(str(e).lower())}'" for e in environments)
            clauses.append(f"| where envVal in ({joined})")

        pedidas = filters.get("missingTags") or []
        if pedidas:
            # "le falta al menos una de estas tags", sin distinguir mayusculas,
            # igual que el camino en memoria. Una tag que no es obligatoria no
            # puede "faltarle" a nadie: si ninguna de las pedidas lo es, el
            # resultado es vacio, no el inventario completo.
            por_nombre = {t.lower(): t for t in MANDATORY_TAGS}
            missing_tags = [por_nombre[t.lower()] for t in pedidas if t.lower() in por_nombre]
            if missing_tags:
                joined = " or ".join(f"not(ok{tag})" for tag in missing_tags)
                clauses.append(f"| where {joined}")
            else:
                clauses.append("| where false")

        if filters.get("onlyNonCompliant"):
            clauses.append("| where not(isCompliant)")

        if filters.get("onlyShadowItCandidates"):
            clauses.append("| where isShadowIt")

        return " ".join(clauses)

    def _resources_from_kql(self, request_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Pagina y filtra en Azure Resource Graph.

        Devuelve None si la consulta falla, para que el llamador recurra al
        camino en memoria.
        """
        sub_ids = self._resolve_scope(request_data.get("subscriptionIds", []))
        if not sub_ids:
            return None
        filters = request_data.get("filters", {})
        page = max(1, request_data.get("page", 1))
        page_size = min(500, max(1, request_data.get("pageSize", 100)))
        # TODO: el camino KQL aun no propaga forceRefresh; ver docs/roadmap.md.
        force_refresh = request_data.get("forceRefresh", False)  # noqa: F841

        prelude = self._kql_governance_prelude()
        sub_name_map = self._get_subscription_name_map(sub_ids)
        where = self._kql_filter_clauses(filters, sub_name_map)
        offset = (page - 1) * page_size

        page_kql = (
            f"{prelude} {where} "
            "| extend provisioningState = tostring(properties.provisioningState) "
            "| extend createdTime = tostring(properties.createdTime) "
            "| extend changedTime = tostring(properties.changedTime) "
            "| project id, name, type, kind, subscriptionId, resourceGroup, location, "
            "  tags, managedBy, sku, provisioningState, createdTime, changedTime "
            "| order by name asc"
        )

        result = self.azure.query_azure_resource_graph_page(
            page_kql, skip=offset, top=page_size, subscriptions=sub_ids
        )
        if not result.get("ok"):
            return None

        items = [self.normalize_resource(row, sub_name_map) for row in result["rows"]]

        return {
            "items": items,
            "total": result["total"],
            "page": page,
            "pageSize": page_size,
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "partialSuccess": False,
            "warnings": [],
            "computedBy": "resource_graph_paged",
        }

    # ------------------------------------------------------------------
    # Cobertura real de Terraform
    # ------------------------------------------------------------------

    def attach_tfstate(self, tfstate) -> None:
        """Inyecta el indice de estados de Terraform (opcional)."""
        self._tfstate = tfstate

    def get_terraform_coverage(
        self, subscription_ids: List[str], force_refresh: bool = False
    ) -> Dict[str, Any]:
        """
        Que parte del inventario gestiona Terraform de verdad.

        La cobertura que mostraba el panel era el porcentaje de recursos con una
        tag que declara la herramienta que los creo: 8% en produccion, un numero
        que no dirige ninguna decision porque mide cuantos equipos etiquetan, no
        cuanta infraestructura esta codificada.

        Aqui se cruza el inventario con los ids que aparecen en los estados
        reales. Un id puede seguir en el estado y ya no existir en Azure —alguien
        lo borro a mano—, asi que no basta con contar ids: se comprueba contra
        Resource Graph cuales existen todavia dentro del scope consultado.

        La cifra vale sobre los estados accesibles, y eso se declara: si un
        equipo guarda el suyo en otra cuenta, sus recursos apareceran como no
        gestionados.
        """
        subs = self._resolve_scope(subscription_ids)
        indice = getattr(self, "_tfstate", None)
        vacio = {
            "available": False,
            "managed_in_inventory": 0,
            "total_resources": 0,
            "coverage_percentage": 0.0,
            "states_read": 0,
            "states_failed": 0,
            "managed_ids_total": 0,
            "managed_out_of_scope": 0,
            "stale_ids": 0,
            "states": [],
            "message": "No hay índice de estados de Terraform disponible.",
        }
        if indice is None or not subs:
            return vacio

        datos = indice.get_index(force=force_refresh)
        if not datos.get("available"):
            return {**vacio, "message": (
                "No se pudieron leer los estados de Terraform: "
                f"{datos.get('reason', 'motivo desconocido')}."
            )}

        en_scope = {s.lower() for s in subs}
        # Solo los ids que el inventario puede contener: los subrecursos y los
        # recursos de extension del estado no son ni cobertura ni obsoletos.
        ids = {i for i in datos["managed_ids"] if governance.es_recurso_inventariable(i)}
        # Un estado puede gestionar recursos de suscripciones que no se estan
        # consultando; solo cuentan los del scope.
        del_scope = [i for i in ids if cost_module.subscription_of(i) in en_scope]

        existentes = self._ids_presentes_en_inventario(del_scope, subs)
        resumen = self._get_summary_cached(subs, force_refresh=False) or {}
        total = int(resumen.get("totalResources") or 0)

        cobertura = round((len(existentes) / total) * 100.0, 1) if total else 0.0
        return {
            "available": True,
            "managed_in_inventory": len(existentes),
            "total_resources": total,
            "coverage_percentage": cobertura,
            "unmanaged_count": max(0, total - len(existentes)),
            "states_read": datos["states_read"],
            "states_failed": datos["states_failed"],
            "managed_ids_total": len(ids),
            "managed_out_of_scope": len(ids) - len(del_scope),
            # Ids que el estado sigue gestionando pero que ya no existen en
            # Azure: alguien borro el recurso sin pasar por Terraform, y el
            # proximo plan lo va a intentar recrear.
            "stale_ids": len(del_scope) - len(existentes),
            "states": datos["states"],
            # Cuentas que no se pudieron listar (normalmente, falta el rol
            # Storage Blob Data Reader). La cifra no las incluye.
            "sources_failed": datos.get("sources_failed", []),
            "message": (
                f"Calculado sobre {datos['states_read']} estado(s) de Terraform en "
                f"{datos['account']}. Un equipo que guarde su estado en otra cuenta "
                "aparecerá como no gestionado."
                + (f" {len(datos['sources_failed'])} cuenta(s) no se pudieron leer."
                   if datos.get("sources_failed") else "")
            ),
        }

    def _ids_presentes_en_inventario(
        self, ids: List[str], subs: List[str]
    ) -> Set[str]:
        """
        Cuales de esos ids existen hoy en Azure.

        Se consulta por lotes: la lista literal de un `in~` tiene un limite de
        tamano, y un tenant con miles de recursos gestionados lo superaria de
        una sola vez.
        """
        presentes: Set[str] = set()
        if not ids:
            return presentes

        lote = int(os.getenv("TFSTATE_ID_BATCH", "150"))
        for inicio in range(0, len(ids), lote):
            trozo = ids[inicio:inicio + lote]
            literal = ", ".join("'" + i.replace("'", "") + "'" for i in trozo)
            consulta = f"resources | where tolower(id) in ({literal}) | project id"
            try:
                filas = self.azure.query_azure_resource_graph(consulta, subscriptions=subs) or []
            except Exception as exc:
                logger.warning(f"[Terraform] Lote de ids sin verificar: {exc}")
                continue
            for fila in filas:
                rid = str(fila.get("id") or "").lower()
                if rid:
                    presentes.add(rid)
        return presentes

    def get_manual_creations(
        self, subscription_ids: List[str], limit: int = 100
    ) -> Dict[str, Any]:
        """
        Recursos creados a mano, con evidencia y no por heuristica.

        Ninguna regla sobre tags puede demostrar que un recurso se creo fuera de
        IaC: solo puede constatar que nadie lo declaro. La tabla
        `resourcechanges` de Resource Graph si registra que identidad creo cada
        recurso, y una identidad con arroba es una persona operando el portal o
        la CLI, mientras que un GUID es un service principal, o sea
        automatizacion.

        La limitacion hay que declararla siempre: Azure conserva esos eventos
        unos catorce dias, asi que esto cubre lo reciente y jamas el inventario
        historico. Por eso se devuelven las fechas de la ventana observada y el
        total de creaciones, para que la interfaz diga sobre que esta hablando
        en lugar de dar un numero suelto.
        """
        subs = self._resolve_scope(subscription_ids)
        vacio = {
            "manualCreations": [],
            "manualCount": 0,
            "automatedCount": 0,
            "totalCreations": 0,
            "windowFrom": None,
            "windowTo": None,
            "available": False,
        }
        if not subs:
            return vacio

        try:
            filas = self.azure.query_azure_resource_graph(
                governance.KQL_CREACIONES, subscriptions=subs
            ) or []
        except Exception as exc:
            logger.warning(f"No se pudo consultar el historial de cambios: {exc}")
            return vacio

        if not filas:
            return vacio

        personas = [f for f in filas if f.get("esPersona")]
        fechas = sorted(str(f.get("cuando")) for f in filas if f.get("cuando"))

        return {
            "manualCreations": [
                {
                    "id": f.get("id"),
                    "name": str(f.get("id") or "").rsplit("/", 1)[-1],
                    "type": f.get("tipoRecurso"),
                    "createdBy": f.get("quien"),
                    "createdAt": f.get("cuando"),
                }
                for f in personas[:limit]
            ],
            "manualCount": len(personas),
            "automatedCount": len(filas) - len(personas),
            "totalCreations": len(filas),
            "windowFrom": fechas[0] if fechas else None,
            "windowTo": fechas[-1] if fechas else None,
            "available": True,
        }

    def get_resources(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Pagina filtrada del inventario, resuelta en Azure cuando es posible."""
        paged = self._resources_from_kql(request_data)
        if paged is not None:
            return paged
        return self.get_resources_from_memory(request_data)

    def get_resources_from_memory(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Implementacion de referencia: descarga el inventario y filtra en memoria."""
        sub_ids = request_data.get("subscriptionIds", [])
        filters = request_data.get("filters", {})
        page = max(1, request_data.get("page", 1))
        page_size = min(500, max(1, request_data.get("pageSize", 100)))
        force_refresh = request_data.get("forceRefresh", False)

        all_resources, warnings = self._fetch_all_resources(sub_ids, force_refresh)
        filtered = self.apply_filters(all_resources, filters)

        total = len(filtered)
        offset = (page - 1) * page_size
        page_items = filtered[offset:offset + page_size]

        return {
            "items": page_items,
            "total": total,
            "page": page,
            "pageSize": page_size,
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "partialSuccess": len(warnings) > 0,
            "warnings": warnings
        }
    
    # ------------------------------------------------------------------
    # KPIs calculados en Azure
    # ------------------------------------------------------------------
    #
    # Contar recursos descargandolos todos obliga a mover cientos de KB y a
    # recorrer cada objeto en Python, y el costo crece con el inventario: en un
    # tenant de treinta suscripciones ese camino no escala. Resource Graph sabe
    # hacer estos agregados del lado del servidor y devuelve una sola fila.
    #
    # Las expresiones de abajo replican, en KQL, exactamente la misma semantica
    # que evaluate_mandatory_tags / classify_shadow_it / build_governance_info,
    # incluidos los valores que se consideran invalidos. La equivalencia se
    # verifica con tests/test_inventory_kpis.py, que compara ambos caminos
    # contra el mismo inventario real.

    @staticmethod
    def _kql_invalid_values() -> str:
        """Lista KQL de valores de tag que no cuentan como presentes."""
        # La cadena vacia se cubre aparte con isnotempty().
        values = sorted(v for v in INVALID_TAG_VALUES if v)
        return ", ".join(f"'{v}'" for v in values)

    def _kql_tag_present(self, tag: str) -> str:
        """Expresion KQL que indica si una tag obligatoria esta presente y es util."""
        # _t es el bag de tags con claves y valores en minusculas, lo que
        # resuelve de una vez la comparacion sin distinguir mayusculas que el
        # codigo Python hace con k.lower() y str(v).strip().lower().
        val = f"trim(' ', tostring(_t['{tag.lower()}']))"
        return f"(isnotempty({val}) and {val} !in ({self._kql_invalid_values()}))"

    def _managed_ids(self) -> Set[str]:
        """
        Ids que Terraform gestiona, segun los estados.

        Se consulta al indice cacheado; si no esta disponible se devuelve un
        conjunto vacio y todo sigue funcionando con la regla de tags, que es
        justo la degradacion que corresponde: sin estados legibles no se puede
        afirmar que nada este gestionado.
        """
        indice = getattr(self, "_tfstate", None)
        if indice is None:
            return set()
        try:
            datos = indice.get_index()
        except Exception as exc:
            logger.warning(f"[Terraform] Indice de estados no disponible: {exc}")
            return set()
        return datos.get("managed_ids") or set()

    def _kql_governance_prelude(self) -> str:
        """Fragmento KQL que deriva cumplimiento, Shadow IT y custodio."""
        invalid = self._kql_invalid_values()
        tag_flags = " ".join(
            f"| extend ok{tag} = {self._kql_tag_present(tag)}" for tag in MANDATORY_TAGS
        )
        present_sum = " + ".join(f"toint(ok{tag})" for tag in MANDATORY_TAGS)

        prod = ", ".join(f"'{e}'" for e in sorted(PRODUCTION_ENVIRONMENTS))
        non_prod = ", ".join(f"'{e}'" for e in sorted(NON_PRODUCTION_ENVIRONMENTS))

        # Las tres senales de gobernanza —evidencia de IaC, recurso derivado y
        # custodio— salen de services/governance.py, la misma definicion que usa
        # el camino Python de arriba y el resumen del agente.
        return (
            "resources "
            "| extend _t = todynamic(tolower(tostring(tags))) "
            "| extend _json = tolower(tostring(tags)) "
            f"{tag_flags} "
            f"| extend presentCount = {present_sum} "
            f"| extend isCompliant = presentCount == {len(MANDATORY_TAGS)} "
            f"| extend enEstado = {governance.kql_gestionado_por_terraform(self._managed_ids())} "
            f"| extend hasIac = enEstado or {governance.kql_tiene_iac()} "
            f"| extend isDerived = {governance.kql_es_derivado()} "
            f"| extend hasOwner = {governance.kql_tiene_custodio(invalid)} "
            "| extend isShadowIt = not(hasIac) and not(isDerived) "
            "  and not(hasOwner) and not(isCompliant) "
            "| extend envVal = trim(' ', tostring(_t['environment'])) "
            f"| extend isProd = envVal in ({prod}) "
            f"| extend isNonProd = envVal in ({non_prod}) "
        )

    def _summary_from_kql(
        self, subscription_ids: List[str], force_refresh: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Calcula los KPIs y las distribuciones con agregados de Resource Graph.

        Devuelve None si Azure no responde, para que el llamador pueda recurrir
        al camino que descarga el inventario completo.
        """
        subscription_ids = self._resolve_scope(subscription_ids)
        if not subscription_ids:
            return None

        prelude = self._kql_governance_prelude()

        # Se agregan de paso los conteos por tag: la matriz de cumplimiento sale
        # de la misma consulta, sin un viaje extra ni la descarga del inventario.
        per_tag = ", ".join(
            f"tag{tag} = countif(ok{tag})" for tag in MANDATORY_TAGS
        )

        kpi_kql = prelude + (
            f"| summarize {per_tag}, "
            "  totalResources = count(), "
            "  compliant = countif(isCompliant), "
            "  shadowIt = countif(isShadowIt), "
            "  noOwner = countif(not(hasOwner)), "
            "  prod = countif(isProd), "
            "  nonProd = countif(isNonProd), "
            "  totalSubscriptions = dcount(subscriptionId), "
            "  totalResourceGroups = dcount(strcat(subscriptionId, '/', resourceGroup)), "
            "  totalRegions = dcount(location)"
        )

        # Las cuatro distribuciones viajan en una sola consulta unida por un
        # discriminador. Separarlas en cuatro consultas paralelas parece
        # equivalente, pero cada ida y vuelta a Resource Graph cuesta unos
        # cientos de milisegundos de latencia: con inventarios chicos esos
        # viajes pesan mas que los datos que ahorran.
        #
        # El valor de Environment se agrupa sin distinguir mayusculas, de modo
        # que 'Dev', 'DEV' y 'dev' cuentan como un solo ambiente. Antes producian
        # tres filas distintas en el panel, que es un defecto y no una
        # caracteristica: el mismo ambiente aparecia fragmentado.
        dist_kql = (
            "resources | summarize count() by k = subscriptionId | top 15 by count_ desc "
            "| extend dim = 'sub' "
            "| union (resources | extend k = tostring(split(type, '/')[-1]) "
            "  | summarize count() by k | top 15 by count_ desc | extend dim = 'type') "
            "| union (resources | summarize count() by k = location "
            "  | top 15 by count_ desc | extend dim = 'region') "
            "| union (resources "
            "  | extend k = trim(' ', tostring(todynamic(tolower(tostring(tags)))['environment'])) "
            "  | extend k = iff(isempty(k), 'Sin definir', k) "
            "  | summarize count() by k | top 15 by count_ desc | extend dim = 'env') "
            "| project dim, k, count_"
        )

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                f_kpi = executor.submit(
                    self.azure.query_azure_resource_graph, kpi_kql, force_refresh, subscription_ids
                )
                f_dist = executor.submit(
                    self.azure.query_azure_resource_graph, dist_kql, force_refresh, subscription_ids
                )
                kpi_rows = f_kpi.result()
                dist_rows = f_dist.result() or []
        except Exception as exc:
            logger.warning(f"KPIs por KQL no disponibles, se usara el camino completo: {exc}")
            return None

        dists: Dict[str, List[Dict[str, Any]]] = {"sub": [], "type": [], "region": [], "env": []}
        for row in dist_rows:
            bucket = dists.get(str(row.get("dim")))
            if bucket is not None:
                bucket.append(row)
        for bucket in dists.values():
            bucket.sort(key=lambda r: int(r.get("count_") or 0), reverse=True)

        if not kpi_rows:
            return None

        k = kpi_rows[0]
        total = int(k.get("totalResources") or 0)
        compliant = int(k.get("compliant") or 0)

        sub_name_map = self._get_subscription_name_map(subscription_ids)

        def to_dist(rows: List[Dict[str, Any]], rename=None) -> List[Dict[str, Any]]:
            out = []
            for row in rows:
                raw_key = row.get("k")
                key = rename(raw_key) if rename else raw_key
                count = int(row.get("count_") or 0)
                out.append({
                    "key": key or "unknown",
                    "count": count,
                    "percentage": round((count / total) * 100, 1) if total else 0,
                })
            return out

        return {
            "totalResources": total,
            "totalSubscriptions": int(k.get("totalSubscriptions") or 0),
            "totalResourceGroups": int(k.get("totalResourceGroups") or 0),
            "totalRegions": int(k.get("totalRegions") or 0),
            "tagCompliancePercentage": round((compliant / total) * 100, 1) if total else 0.0,
            "nonCompliantResources": total - compliant,
            "shadowItCandidates": int(k.get("shadowIt") or 0),
            "resourcesWithoutOwnerCandidate": int(k.get("noOwner") or 0),
            "productionResources": int(k.get("prod") or 0),
            "nonProductionResources": int(k.get("nonProd") or 0),
            "bySubscription": to_dist(dists["sub"], rename=lambda v: sub_name_map.get(v, v)),
            "byResourceType": to_dist(dists["type"]),
            "byRegion": to_dist(dists["region"]),
            "byEnvironment": to_dist(dists["env"]),
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "partialSuccess": False,
            "warnings": [],
            "computedBy": "resource_graph_summarize",
            # Insumo de get_tag_compliance, ya calculado aqui.
            "_tagCounts": {tag: int(k.get(f"tag{tag}") or 0) for tag in MANDATORY_TAGS},
        }

    def _get_summary_cached(
        self, subscription_ids: List[str], force_refresh: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Agregado de KPIs con cache propia.

        El resumen y la matriz de tags se piden casi siempre juntos al abrir la
        pestana; cachear aqui evita repetir la consulta para cada uno.
        """
        # La clave se calcula sobre el alcance resuelto: pedir "todas" y pedir la
        # lista explicita deben compartir entrada de cache, no duplicarla.
        cache_key = self._cache_key("summary_kql", self._resolve_scope(subscription_ids))
        if not force_refresh:
            cached = self._get_cached(cache_key)
            if cached is not None:
                return cached

        fast = self._summary_from_kql(subscription_ids, force_refresh)
        if fast is not None:
            self._set_cached(cache_key, fast)
        return fast

    def get_summary(self, subscription_ids: List[str], force_refresh: bool = False) -> Dict[str, Any]:
        """
        KPIs del inventario.

        Se prefieren los agregados calculados en Azure; si esa via falla se cae
        al recorrido completo en memoria, que sigue siendo la implementacion de
        referencia contra la que se valida la equivalencia.
        """
        fast = self._get_summary_cached(subscription_ids, force_refresh)
        if fast is not None:
            # _tagCounts es insumo interno; no forma parte del contrato del API.
            return {k: v for k, v in fast.items() if k != "_tagCounts"}
        return self.get_summary_from_resources(subscription_ids, force_refresh)

    def get_summary_from_resources(self, subscription_ids: List[str], force_refresh: bool = False) -> Dict[str, Any]:
        """Implementacion de referencia: descarga el inventario y cuenta en memoria."""
        all_resources, warnings = self._fetch_all_resources(subscription_ids, force_refresh)
        
        total = len(all_resources)
        subs = set()
        rgs = set()
        regions = set()
        compliant = 0
        shadow_it = 0
        no_owner = 0
        prod_count = 0
        non_prod_count = 0
        
        by_sub = {}
        by_type = {}
        by_region = {}
        by_env = {}
        
        for r in all_resources:
            sub_id = r.get("subscriptionId", "")
            sub_name = r.get("subscriptionName", sub_id)
            subs.add(sub_id)
            rgs.add(f"{sub_id}/{r.get('resourceGroup', '')}")
            loc = r.get("location", "unknown")
            regions.add(loc)
            
            if r.get("mandatoryTags", {}).get("isCompliant"):
                compliant += 1
            if r.get("governance", {}).get("isShadowItCandidate"):
                shadow_it += 1
            if not r.get("governance", {}).get("hasOwnerCandidate"):
                no_owner += 1
            if r.get("governance", {}).get("isProduction"):
                prod_count += 1
            if r.get("governance", {}).get("isNonProduction"):
                non_prod_count += 1
            
            by_sub[sub_name] = by_sub.get(sub_name, 0) + 1
            res_type = r.get("typeDisplayName", r.get("type", "unknown"))
            by_type[res_type] = by_type.get(res_type, 0) + 1
            by_region[loc] = by_region.get(loc, 0) + 1
            # Se agrupa sin distinguir mayusculas, igual que el camino KQL:
            # 'Dev' y 'dev' son el mismo ambiente y deben sumar en una sola fila.
            env = (r.get("environment") or "").strip().lower() or "Sin definir"
            by_env[env] = by_env.get(env, 0) + 1
        
        def to_dist(d: Dict[str, int], top_n: int = 15) -> List[Dict[str, Any]]:
            sorted_items = sorted(d.items(), key=lambda x: x[1], reverse=True)[:top_n]
            return [{"key": k, "count": v, "percentage": round((v / total) * 100, 1) if total > 0 else 0} for k, v in sorted_items]
        
        compliance_pct = round((compliant / total) * 100, 1) if total > 0 else 0.0
        
        return {
            "totalResources": total,
            "totalSubscriptions": len(subs),
            "totalResourceGroups": len(rgs),
            "totalRegions": len(regions),
            "tagCompliancePercentage": compliance_pct,
            "nonCompliantResources": total - compliant,
            "shadowItCandidates": shadow_it,
            "resourcesWithoutOwnerCandidate": no_owner,
            "productionResources": prod_count,
            "nonProductionResources": non_prod_count,
            "bySubscription": to_dist(by_sub),
            "byResourceType": to_dist(by_type),
            "byRegion": to_dist(by_region),
            "byEnvironment": to_dist(by_env),
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "partialSuccess": len(warnings) > 0,
            "warnings": warnings
        }
    
    def get_tag_compliance(self, subscription_ids: List[str], force_refresh: bool = False) -> Dict[str, Any]:
        """
        Matriz de cumplimiento de las tags obligatorias.

        Se resuelve con el mismo agregado que produce los KPIs, que ya viene
        cacheado por el resumen. Antes obligaba a tener el inventario completo en
        memoria, que es el costo que domina en tenants grandes.
        """
        summary = self._get_summary_cached(subscription_ids, force_refresh)
        if summary is not None and "_tagCounts" in summary:
            total = summary["totalResources"]
            matrix = []
            for tag in MANDATORY_TAGS:
                present = summary["_tagCounts"].get(tag, 0)
                matrix.append({
                    "tag": tag,
                    "present": present,
                    "missing": total - present,
                    "compliancePercentage": round((present / total) * 100, 1) if total else 0.0,
                })
            return {
                "requiredTags": MANDATORY_TAGS,
                "matrix": matrix,
                "totalResources": total,
                "overallCompliancePercentage": summary["tagCompliancePercentage"],
                "lastUpdated": summary["lastUpdated"],
                "partialSuccess": False,
                "warnings": [],
            }
        return self.get_tag_compliance_from_resources(subscription_ids, force_refresh)

    def get_tag_compliance_from_resources(self, subscription_ids: List[str], force_refresh: bool = False) -> Dict[str, Any]:
        """Implementacion de referencia, sobre el inventario descargado."""
        all_resources, warnings = self._fetch_all_resources(subscription_ids, force_refresh)
        total = len(all_resources)
        
        tag_counts = {tag: {"present": 0, "missing": 0} for tag in MANDATORY_TAGS}
        
        for r in all_resources:
            missing_list = r.get("mandatoryTags", {}).get("missing", [])
            for tag in MANDATORY_TAGS:
                if tag in missing_list:
                    tag_counts[tag]["missing"] += 1
                else:
                    tag_counts[tag]["present"] += 1
        
        matrix = []
        for tag in MANDATORY_TAGS:
            p = tag_counts[tag]["present"]
            m = tag_counts[tag]["missing"]
            pct = round((p / total) * 100, 1) if total > 0 else 0.0
            matrix.append({"tag": tag, "present": p, "missing": m, "compliancePercentage": pct})
        
        compliant_count = sum(1 for r in all_resources if r.get("mandatoryTags", {}).get("isCompliant"))
        overall_pct = round((compliant_count / total) * 100, 1) if total > 0 else 0.0
        
        return {
            "requiredTags": MANDATORY_TAGS,
            "matrix": matrix,
            "totalResources": total,
            "overallCompliancePercentage": overall_pct,
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "partialSuccess": len(warnings) > 0,
            "warnings": warnings
        }
    
    def export_csv(self, subscription_ids: List[str], filters: Dict[str, Any] = None) -> str:
        """Generates CSV content string from inventory."""
        all_resources, _ = self._fetch_all_resources(subscription_ids)
        if filters:
            all_resources = self.apply_filters(all_resources, filters)
        
        headers = [
            "subscriptionName", "subscriptionId", "resourceGroup", "name", "type",
            "location", "environment", *MANDATORY_TAGS,
            "missingTags", "compliancePercentage", "isShadowItCandidate",
            "shadowItReason", "id"
        ]
        
        lines = [",".join(headers)]
        for r in all_resources:
            missing = "; ".join(r.get("mandatoryTags", {}).get("missing", []))
            compliance = str(r.get("mandatoryTags", {}).get("compliancePercentage", 0))
            is_shadow = str(r.get("governance", {}).get("isShadowItCandidate", False))
            shadow_reason = r.get("governance", {}).get("shadowItReason") or ""
            
            row = [
                self._csv_escape(r.get("subscriptionName", "")),
                self._csv_escape(r.get("subscriptionId", "")),
                self._csv_escape(r.get("resourceGroup", "")),
                self._csv_escape(r.get("name", "")),
                self._csv_escape(r.get("type", "")),
                self._csv_escape(r.get("location", "")),
                self._csv_escape(r.get("environment") or ""),
                *(self._csv_escape((r.get("tagValues") or {}).get(t) or "") for t in MANDATORY_TAGS),
                self._csv_escape(missing),
                compliance,
                is_shadow,
                self._csv_escape(shadow_reason),
                self._csv_escape(r.get("id", ""))
            ]
            lines.append(",".join(row))
        
        return "\n".join(lines)
    
    @staticmethod
    def _csv_escape(val: str) -> str:
        val = str(val).replace('"', '""')
        if ',' in val or '"' in val or '\n' in val:
            return f'"{val}"'
        return val

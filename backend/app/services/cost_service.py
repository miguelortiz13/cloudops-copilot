"""
CostService — Costos reales desde Azure Cost Management, con cobertura explicita.

Este modulo reemplaza las heuristicas de costo que existian en el reporte de
FinOps (recursos x $15.50/mes, $8 por disco, etc.) por consultas reales a la
Cost Management Query API.

Principios de diseno:

* Cobertura parcial como caso normal, no como excepcion. El Service Principal de
  la plataforma tiene lectura global sobre el tenant pero permisos de Cost
  Management sobre unas pocas suscripciones. Por eso NUNCA se reporta un total
  como "facturacion real" sin decir a cuantas suscripciones alcanza: cada
  consulta devuelve un bloque `coverage` con las suscripciones cubiertas, las
  denegadas y las que fallaron por otro motivo. Un total que solo cubre una de
  treinta suscripciones no debe poder confundirse con el gasto completo.
* Degradacion honesta. Donde no hay permiso no se inventa un numero: el
  consumidor debe marcar esos recursos como estimados.
* Cache agresiva. Cost Management consolida el gasto una vez al dia y aplica
  limites de tasa muy estrictos (429 con Retry-After). Un TTL de 6 horas evita
  agotar la cuota. Las denegaciones se cachean aparte para no reintentar en cada
  reporte decenas de suscripciones que se sabe que responderan 403.
* Metrica portable. Las suscripciones Enterprise Agreement exponen la metrica
  como "PreTaxCost" y las Microsoft Customer Agreement / Pay-As-You-Go como
  "Cost". Se intenta "Cost" y se reintenta con "PreTaxCost" si Azure rechaza la
  peticion, de modo que el modulo funciona en cualquier tipo de contrato.
"""

import hashlib
import json
import os

import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import requests

from app.core import config

COST_API_VERSION = "2023-03-01"
MANAGEMENT_ROOT = "https://management.azure.com"

# Cost Management consolida una vez al dia; 6 horas de cache es holgado.
DEFAULT_TTL_SECONDS = int(os.getenv("COST_CACHE_TTL_SECONDS", "21600"))

# Ventana por defecto de analisis de gasto.
DEFAULT_WINDOW_DAYS = int(os.getenv("COST_WINDOW_DAYS", "30"))

# La API es lenta con agrupaciones grandes; damos margen pero acotado para no
# colgar al App Service detras del gateway de Azure (que corta a los 230s).
REQUEST_TIMEOUT = float(os.getenv("COST_REQUEST_TIMEOUT", "45"))

MAX_RETRIES = 3

# Tiempo maximo que una peticion puede pasar esperando a que Cost Management
# levante un limite de tasa. Agotado el presupuesto se devuelve "throttled" de
# inmediato: es preferible responder con datos de cache o marcados como
# estimados que arriesgar el corte de 230s del gateway de App Service.
MAX_THROTTLE_WAIT_SECONDS = float(os.getenv("COST_MAX_THROTTLE_WAIT", "25"))

# Cuanto se recuerda que una suscripcion no tiene permisos de Cost Management.
# Evita reintentar en cada reporte decenas de suscripciones sin acceso, pero es
# lo bastante corto para que un permiso recien otorgado se detecte solo.
DENIAL_TTL_SECONDS = int(os.getenv("COST_DENIAL_TTL_SECONDS", "3600"))

# Cost Management limita con dureza las consultas concurrentes por suscripcion y
# responde 429 con facilidad. Un semaforo de modulo mantiene el paralelismo del
# resto del reporte (Resource Graph, Monitor) sin castigar a esta API.
_QUERY_SEMAPHORE = threading.Semaphore(int(os.getenv("COST_MAX_CONCURRENT", "2")))

# Cuantas suscripciones se procesan en paralelo. El semaforo de arriba es el que
# realmente acota la presion sobre la API; este solo evita crear decenas de
# hilos en tenants con muchas suscripciones.
MAX_SUB_WORKERS = int(os.getenv("COST_SUB_WORKERS", "8"))

EMPTY_COVERAGE: Dict[str, List[str]] = {"covered": [], "denied": [], "failed": []}

# Ritmo de la precarga en segundo plano: segundos de pausa entre suscripciones.
# Con 2.5s, diez de las treinta suscripciones del tenant se quedaban sin dato en
# cada ciclo por limite de tasa. Nadie espera esta precarga, asi que ir despacio
# no le cuesta nada al usuario y deja cuota libre para las peticiones
# interactivas.
WARM_PACE_SECONDS = float(os.getenv("COST_WARM_PACE_SECONDS", "9"))

# Las suscripciones que fallan por limite de tasa se reintentan al terminar la
# primera pasada, en lugar de esperar seis horas al siguiente ciclo: un 429 no
# dice nada sobre los permisos, solo que en ese momento no habia cuota. El
# reintento espera un respiro y va al doble de lento, y su resultado se fusiona
# en la entrada de cache del scope completo para que el panel lo vea.
WARM_RETRY_ENABLED = os.getenv("COST_WARM_RETRY", "true").strip().lower() in ("1", "true", "yes")
WARM_RETRY_BACKOFF_SECONDS = float(os.getenv("COST_WARM_RETRY_BACKOFF", "60"))
WARM_RETRY_PACE_FACTOR = float(os.getenv("COST_WARM_RETRY_PACE_FACTOR", "2"))

# La cache vivia solo en memoria, asi que cada reinicio la vaciaba y el arranque
# volvia a consultar las ~56 llamadas de la precarga. Medido: cuatro despliegues
# en dos horas agotaron la cuota y un ciclo que venia cubriendo 24 de 30
# suscripciones bajo a 9. Persistirla en el File Share ya montado —el mismo que
# guarda el Excel y el historico de KPIs— hace que un reinicio arranque con el
# gasto ya consolidado, sin crear ningun recurso nuevo en Azure.
CACHE_PERSIST_ENABLED = os.getenv("COST_CACHE_PERSIST", "true").strip().lower() in ("1", "true", "yes")

# Pasada esta edad una entrada guardada se descarta al cargar. El TTL decide
# cuando refrescar; esto decide cuando el dato ya no sirve ni como respaldo ante
# un 429. Cost Management consolida a diario, asi que una semana es holgado.
CACHE_MAX_AGE_SECONDS = int(os.getenv("COST_CACHE_MAX_AGE_SECONDS", str(7 * 24 * 3600)))


# ----------------------------------------------------------------------
# Atribucion de costo por recurso
# ----------------------------------------------------------------------
#
# Estas tres funciones son la unica definicion de "cuanto cuesta este recurso y
# de donde sale esa cifra" en toda la plataforma. Las usan el reporte de FinOps
# del panel y el chat del agente. Antes cada uno tenia la suya: el panel
# distinguia gasto facturado de estimacion, y el chat sumaba estimaciones por
# SKU y las publicaba bajo el nombre del gasto real, de modo que la misma
# pregunta daba dos cifras distintas segun donde se hiciera.


def subscription_of(resource_id: str) -> str:
    """
    Extrae el id de suscripcion de un resource id de Azure.

    Los ids tienen la forma /subscriptions/<sub>/resourceGroups/... Saber a que
    suscripcion pertenece cada recurso es lo que permite decidir, fila por fila,
    si su costo viene de la factura o de una estimacion.
    """
    parts = str(resource_id or "").lower().split("/")
    if len(parts) > 2 and parts[1] == "subscriptions":
        return parts[2]
    return ""


def monthly_from_window(cost: float, window_days: int) -> float:
    """Normaliza el gasto de la ventana observada a un equivalente mensual."""
    if not window_days:
        return 0.0
    return round((cost / window_days) * 30.0, 2)


def attach_costs(
    items: List[Dict[str, Any]],
    cost_map: Dict[str, float],
    window_days: int,
    covered_subs: Set[str],
    fallback: Callable[[Dict[str, Any]], float],
) -> Dict[str, float]:
    """
    Anota cada recurso con su costo mensual y devuelve los totales.

    La decision de usar facturacion o estimacion se toma **por recurso**, segun
    si su suscripcion esta cubierta por Cost Management. En un tenant donde el
    Service Principal solo tiene permisos de costo sobre unas pocas de treinta
    suscripciones, tratar la disponibilidad como un unico booleano global haria
    pasar por "facturacion real" un total que mezcla suscripciones medidas con
    suscripciones estimadas.

    Cada elemento recibe `monthly_cost_usd` y `cost_basis` ('actual' o
    'estimated'), y se devuelve `{"total", "actual", "estimated"}` para que el
    consumidor pueda decir que parte de la cifra respalda la factura.
    """
    totals = {"total": 0.0, "actual": 0.0, "estimated": 0.0}
    covered_subs = {str(s).lower() for s in (covered_subs or set())}

    for item in items:
        resource_id = str(item.get("id") or "").lower()
        covered = subscription_of(resource_id) in covered_subs
        billed = cost_map.get(resource_id) if covered else None

        if covered and billed is not None:
            monthly = monthly_from_window(billed, window_days)
            item["cost_basis"] = "actual"
            totals["actual"] += monthly
        elif covered:
            # Suscripcion medida y el recurso no aparece en la factura: no
            # genero cargo en la ventana observada. Cero es el dato real.
            monthly = 0.0
            item["cost_basis"] = "actual"
        else:
            monthly = round(float(fallback(item)), 2)
            item["cost_basis"] = "estimated"
            totals["estimated"] += monthly

        item["monthly_cost_usd"] = monthly
        totals["total"] += monthly

    return {k: round(v, 2) for k, v in totals.items()}


class CostService:
    """Consulta y cachea el gasto real de Azure Cost Management."""

    def __init__(self, azure, cache_dir: Optional[str] = None):
        self.azure = azure
        self._cache: Dict[Tuple, Tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._ttl = DEFAULT_TTL_SECONDS
        # subscription_id -> momento en que Azure nego el acceso. Esto no se
        # persiste: su TTL es de una hora y un permiso recien otorgado debe
        # detectarse solo.
        self._denied: Dict[str, float] = {}
        self._cache_dir = self._resolve_cache_dir(cache_dir)
        self._load_from_disk()

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_cache_dir(explicit: Optional[str]) -> Optional[Path]:
        """
        Donde vive la cache entre reinicios.

        Se prefiere el File Share persistente que ya esta montado; sin el, un
        directorio local que al menos sirve en desarrollo. Si no se puede
        escribir en ninguno, el servicio funciona igual que antes: en memoria.
        """
        if not CACHE_PERSIST_ENABLED:
            return None

        candidatos = []
        if explicit:
            candidatos.append(Path(explicit))
        # DATA_DIR (antes EXCEL_STORAGE_DIR): File Share en Azure, backend/data en local.
        candidatos.append(config.DATA_DIR / "cost_cache")

        for candidato in candidatos:
            try:
                candidato.mkdir(parents=True, exist_ok=True)
                return candidato
            except Exception as exc:
                print(f"[CostService] No se pudo usar {candidato} para la cache: {exc}")
        return None

    @staticmethod
    def _key_to_filename(key: Tuple) -> str:
        """Nombre estable y corto para una clave de cache."""
        return hashlib.sha1(repr(key).encode("utf-8")).hexdigest()[:20] + ".json"

    def _load_from_disk(self) -> None:
        """Repuebla la cache en memoria con lo que quedo guardado."""
        if self._cache_dir is None:
            return

        cargadas = 0
        ahora = time.time()
        try:
            archivos = sorted(self._cache_dir.glob("*.json"))
        except Exception as exc:
            print(f"[CostService] No se pudo leer la cache persistida: {exc}")
            return

        for archivo in archivos:
            try:
                with open(archivo, "r", encoding="utf-8") as fh:
                    registro = json.load(fh)
                guardado = float(registro["saved_at"])
                if ahora - guardado > CACHE_MAX_AGE_SECONDS:
                    archivo.unlink(missing_ok=True)
                    continue
                clave = self._deserializar_clave(registro["key"])
                with self._lock:
                    self._cache[clave] = (guardado, registro["payload"])
                cargadas += 1
            except Exception as exc:
                # Un archivo corrupto no puede impedir el arranque: se descarta.
                print(f"[CostService] Entrada de cache ilegible ({archivo.name}): {exc}")
                try:
                    archivo.unlink(missing_ok=True)
                except Exception:
                    pass

        if cargadas:
            print(f"[CostService] {cargadas} entrada(s) de costo recuperadas del almacenamiento.")

    @staticmethod
    def _serializar_clave(key: Tuple) -> List[Any]:
        """Las claves son tuplas con tuplas dentro; JSON solo entiende listas."""
        return [list(parte) if isinstance(parte, tuple) else parte for parte in key]

    @staticmethod
    def _deserializar_clave(bruta: List[Any]) -> Tuple:
        return tuple(tuple(parte) if isinstance(parte, list) else parte for parte in bruta)

    def _persist(self, key: Tuple, guardado: float, value: Any) -> None:
        """
        Guarda una entrada. Nunca propaga: la cache es una optimizacion.

        La escritura es atomica (temporal + replace) para que un reinicio en
        mitad del volcado no deje un JSON truncado que despues haya que
        descartar.
        """
        if self._cache_dir is None:
            return
        destino = self._cache_dir / self._key_to_filename(key)
        temporal = destino.with_suffix(".tmp")
        try:
            registro = {
                "key": self._serializar_clave(key),
                "saved_at": guardado,
                "payload": value,
            }
            with open(temporal, "w", encoding="utf-8") as fh:
                json.dump(registro, fh, ensure_ascii=False)
            os.replace(temporal, destino)
        except Exception as exc:
            print(f"[CostService] No se pudo persistir la cache de costos: {exc}")
            try:
                temporal.unlink(missing_ok=True)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _get_cached(self, key: Tuple) -> Optional[Any]:
        with self._lock:
            entry = self._cache.get(key)
            if entry and (time.time() - entry[0]) < self._ttl:
                return entry[1]
        return None

    def _get_stale(self, key: Tuple) -> Optional[Any]:
        """
        Ultimo valor conocido aunque haya vencido el TTL.

        Se usa cuando Cost Management rechaza la consulta por limite de tasa: un
        dato de gasto de hace unas horas sigue siendo facturacion real y es muy
        preferible a caer a estimaciones por SKU.
        """
        with self._lock:
            entry = self._cache.get(key)
            return entry[1] if entry else None

    def _set_cached(self, key: Tuple, value: Any) -> None:
        guardado = time.time()
        with self._lock:
            self._cache[key] = (guardado, value)
        self._persist(key, guardado, value)

    def _is_denied(self, subscription_id: str) -> bool:
        with self._lock:
            ts = self._denied.get(subscription_id)
            if ts is None:
                return False
            if time.time() - ts > DENIAL_TTL_SECONDS:
                del self._denied[subscription_id]
                return False
            return True

    def _mark_denied(self, subscription_id: str) -> None:
        with self._lock:
            self._denied[subscription_id] = time.time()

    # ------------------------------------------------------------------
    # Infraestructura de consulta
    # ------------------------------------------------------------------

    def _token(self) -> Optional[str]:
        """Obtiene un bearer token de ARM reutilizando las credenciales del agente."""
        if not getattr(self.azure, "azure_connected", False):
            return None
        credentials = getattr(self.azure, "azure_credentials", None)
        if not credentials:
            return None
        try:
            return credentials.get_token(f"{MANAGEMENT_ROOT}/.default").token
        except Exception as exc:  # pragma: no cover - depende del entorno Azure
            print(f"[CostService] No se pudo obtener token de ARM: {exc}")
            return None

    @staticmethod
    def _window(days: int) -> Tuple[str, str]:
        """Devuelve la ventana [desde, hasta) en ISO 8601 UTC."""
        end = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        start = end - timedelta(days=days)
        return start.isoformat(), end.isoformat()

    def _post_query(
        self, scope: str, payload: Dict[str, Any], token: str
    ) -> Dict[str, Any]:
        """
        Ejecuta una consulta contra Cost Management siguiendo `nextLink` y
        respetando los reintentos que pida Azure.

        Devuelve `{"status": ..., "columns": [...], "rows": [...]}`.
        """
        url = f"{MANAGEMENT_ROOT}{scope}/providers/Microsoft.CostManagement/query?api-version={COST_API_VERSION}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        columns: List[Dict[str, Any]] = []
        rows: List[List[Any]] = []
        attempts = 0
        throttle_deadline = time.time() + MAX_THROTTLE_WAIT_SECONDS

        while url:
            try:
                with _QUERY_SEMAPHORE:
                    response = requests.post(
                        url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
                    )
            except requests.RequestException as exc:
                return {"status": "error", "message": str(exc), "columns": [], "rows": []}

            if response.status_code in (401, 403):
                # Falta el rol Cost Management Reader sobre el scope.
                return {
                    "status": "unauthorized",
                    "message": "Sin permisos de Cost Management sobre este scope.",
                    "columns": [],
                    "rows": [],
                }

            if response.status_code == 429:
                attempts += 1
                retry_after = response.headers.get(
                    "x-ms-ratelimit-microsoft.consumption-retry-after"
                ) or response.headers.get("Retry-After", "20")
                try:
                    delay = min(float(retry_after), 60.0)
                except ValueError:
                    delay = 20.0

                # Se abandona si se agotaron los reintentos o si esperar
                # excederia el presupuesto de tiempo de la peticion.
                if attempts > MAX_RETRIES or time.time() + delay > throttle_deadline:
                    return {
                        "status": "throttled",
                        "message": "Cost Management aplico limite de tasa (429).",
                        "columns": [],
                        "rows": [],
                    }
                time.sleep(delay)
                continue

            if response.status_code == 400:
                return {
                    "status": "bad_request",
                    "message": response.text[:500],
                    "columns": [],
                    "rows": [],
                }

            if response.status_code != 200:
                return {
                    "status": "error",
                    "message": f"HTTP {response.status_code}: {response.text[:500]}",
                    "columns": [],
                    "rows": [],
                }

            body = response.json().get("properties", {}) or {}
            if not columns:
                columns = body.get("columns", []) or []
            rows.extend(body.get("rows", []) or [])

            # La paginacion de Cost Management viaja en el cuerpo, no en headers.
            url = body.get("nextLink") or ""
            attempts = 0

        return {"status": "success", "columns": columns, "rows": rows}

    def _query_grouped(
        self,
        subscription_id: str,
        grouping: Optional[List[Dict[str, str]]],
        days: int,
        token: str,
        granularity: str = "None",
    ) -> Dict[str, Any]:
        """
        Consulta el gasto agrupado, resolviendo la diferencia de nombre de
        metrica entre contratos EA (PreTaxCost) y MCA/PAYG (Cost).
        """
        start, end = self._window(days)
        scope = f"/subscriptions/{subscription_id}"

        for metric in ("Cost", "PreTaxCost"):
            payload: Dict[str, Any] = {
                "type": "ActualCost",
                "timeframe": "Custom",
                "timePeriod": {"from": start, "to": end},
                "dataset": {
                    "granularity": granularity,
                    "aggregation": {
                        "totalCost": {"name": metric, "function": "Sum"}
                    },
                },
            }
            if grouping:
                payload["dataset"]["grouping"] = grouping

            result = self._post_query(scope, payload, token)
            if result["status"] == "bad_request" and metric == "Cost":
                # Contrato EA: reintentar con la metrica PreTaxCost.
                continue
            return result

        return {
            "status": "error",
            "message": "Ninguna metrica de costo aceptada.",
            "columns": [],
            "rows": [],
        }

    def _run_per_subscription(
        self,
        subscription_ids: List[str],
        worker: Callable[[str, str], Dict[str, Any]],
        token: str,
        pace_seconds: float = 0.0,
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[str]]]:
        """
        Ejecuta `worker(subscription_id, token)` sobre cada suscripcion y
        clasifica el resultado en cubiertas / denegadas / fallidas.

        Las suscripciones que ya se sabe que no tienen permiso no se vuelven a
        consultar hasta que expire DENIAL_TTL_SECONDS: en un tenant de treinta
        suscripciones con permisos de Cost Management en una sola, reintentarlas
        en cada reporte solo agrega latencia y ruido en los logs.
        """
        coverage: Dict[str, List[str]] = {"covered": [], "denied": [], "failed": []}
        results: Dict[str, Dict[str, Any]] = {}

        pending: List[str] = []
        for subscription_id in subscription_ids:
            if self._is_denied(subscription_id):
                coverage["denied"].append(subscription_id)
            else:
                pending.append(subscription_id)

        if pending and pace_seconds > 0:
            # Modo precarga: una suscripcion a la vez, con pausa entre llamadas.
            # Cost Management responde 429 con facilidad y en segundo plano no
            # hay nadie esperando, asi que conviene ir despacio y no gastar la
            # cuota que necesitan las peticiones interactivas.
            for idx, sub_id in enumerate(pending):
                if idx:
                    time.sleep(pace_seconds)
                try:
                    result = worker(sub_id, token)
                except Exception as exc:
                    result = {"status": "error", "message": str(exc)}
                results[sub_id] = result
                status = result.get("status")
                if status == "success":
                    coverage["covered"].append(sub_id)
                elif status == "unauthorized":
                    self._mark_denied(sub_id)
                    coverage["denied"].append(sub_id)
                else:
                    coverage["failed"].append(sub_id)
            return results, coverage

        if pending:
            workers = min(MAX_SUB_WORKERS, len(pending))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(worker, sub_id, token): sub_id
                    for sub_id in pending
                }
                for future, sub_id in futures.items():
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {"status": "error", "message": str(exc)}

                    results[sub_id] = result
                    status = result.get("status")
                    if status == "success":
                        coverage["covered"].append(sub_id)
                    elif status == "unauthorized":
                        self._mark_denied(sub_id)
                        coverage["denied"].append(sub_id)
                    else:
                        coverage["failed"].append(sub_id)
                        print(
                            f"[CostService] Suscripcion {sub_id}: {status} — "
                            f"{str(result.get('message', ''))[:160]}"
                        )

        return results, coverage

    @staticmethod
    def _coverage_status(coverage: Dict[str, List[str]]) -> str:
        """
        Traduce la cobertura a un estado unico.

        * `success`      — todas las suscripciones del scope aportaron datos.
        * `partial`      — algunas si y otras no: el total NO es el gasto completo.
        * `unauthorized` — ninguna tiene permisos de Cost Management.
        * `error`        — ninguna respondio por limite de tasa u otro fallo.
        """
        covered = len(coverage["covered"])
        denied = len(coverage["denied"])
        failed = len(coverage["failed"])

        if covered and not denied and not failed:
            return "success"
        if covered:
            return "partial"
        if denied and not failed:
            return "unauthorized"
        if failed:
            return "error"
        return "no_subscriptions"

    @staticmethod
    def _index_of(columns: List[Dict[str, Any]], name: str) -> Optional[int]:
        """Localiza una columna por nombre; el orden que devuelve Azure varia."""
        for idx, column in enumerate(columns):
            if str(column.get("name", "")).lower() == name.lower():
                return idx
        return None

    def _cost_index(self, columns: List[Dict[str, Any]]) -> Optional[int]:
        """Indice de la columna de costo, sea EA (PreTaxCost) o MCA/PAYG (Cost)."""
        idx = self._index_of(columns, "Cost")
        return idx if idx is not None else self._index_of(columns, "PreTaxCost")

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------

    def get_cost_by_resource(
        self,
        subscription_ids: List[str],
        days: int = DEFAULT_WINDOW_DAYS,
        pace_seconds: float = 0.0,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Gasto real por recurso en la ventana indicada.

        Devuelve `{"status", "currency", "window_days", "costs", "coverage"}` con
        los resource id en minusculas para cruzarlos con Resource Graph.
        `coverage` indica sobre que suscripciones alcanza el dato.
        """
        subscription_ids = [s for s in (subscription_ids or []) if s]
        if not subscription_ids:
            return {"status": "no_subscriptions", "currency": "USD",
                    "window_days": days, "costs": {}, "coverage": dict(EMPTY_COVERAGE)}

        cache_key = ("by_resource", tuple(sorted(subscription_ids)), days)
        if not force:
            cached = self._get_cached(cache_key)
            if cached is not None:
                return cached

        token = self._token()
        if not token:
            return {"status": "offline", "currency": "USD",
                    "window_days": days, "costs": {}, "coverage": dict(EMPTY_COVERAGE)}

        results, coverage = self._run_per_subscription(
            subscription_ids,
            lambda sub_id, tok: self._query_grouped(
                sub_id, [{"type": "Dimension", "name": "ResourceId"}], days, tok
            ),
            token,
            pace_seconds,
        )

        costs: Dict[str, float] = {}
        currency = "USD"
        for sub_id in coverage["covered"]:
            result = results[sub_id]
            columns = result.get("columns", [])
            cost_idx = self._cost_index(columns)
            key_idx = self._index_of(columns, "ResourceId")
            currency_idx = self._index_of(columns, "Currency")
            if cost_idx is None or key_idx is None:
                continue
            for row in result.get("rows", []):
                try:
                    key = str(row[key_idx] or "").lower()
                    if not key:
                        continue
                    costs[key] = costs.get(key, 0.0) + float(row[cost_idx] or 0.0)
                    if currency_idx is not None and row[currency_idx]:
                        currency = str(row[currency_idx])
                except (IndexError, TypeError, ValueError):
                    continue

        payload = {
            "status": self._coverage_status(coverage),
            "currency": currency,
            "window_days": days,
            "costs": costs,
            "coverage": coverage,
        }

        if coverage["covered"]:
            self._set_cached(cache_key, payload)
            return payload

        # Ninguna suscripcion respondio. Si el motivo es falta de permisos, un
        # dato viejo tampoco se refrescara nunca y conviene decir la verdad; si
        # fue limite de tasa o un fallo transitorio, se reutiliza lo ultimo bueno.
        if payload["status"] != "unauthorized":
            stale = self._get_stale(cache_key)
            if stale is not None:
                return {**stale, "stale": True}
        return payload

    def costs_for(
        self, subscription_ids: List[str], allow_query: bool = True
    ) -> Dict[str, Any]:
        """
        Gasto por recurso de estas suscripciones, prefiriendo lo ya precargado.

        La cache se indexa por el scope completo de la consulta, asi que pedir
        el costo de una sola suscripcion no acierta en la entrada que dejo la
        precarga de las treinta: sin esto, cada pregunta del chat por un grupo
        de recursos lanzaba una consulta viva a Cost Management que competia con
        la precarga por la misma cuota, recibia 429 y devolvia estimaciones. El
        chat decia "estimado 800" del mismo grupo que el panel mostraba con
        factura real.

        Aqui se recorren las entradas de cache ya existentes —de cualquier
        scope— y se toma de ellas el gasto de las suscripciones pedidas. No se
        exige que la entrada este dentro del TTL: un dato de gasto de hace unas
        horas sigue siendo facturacion real, y Cost Management solo lo consolida
        una vez al dia. Solo se consulta a la API lo que ninguna entrada cubra.
        """
        pedidas = {str(s).lower() for s in (subscription_ids or []) if s}
        if not pedidas:
            return {"status": "no_subscriptions", "currency": "USD",
                    "window_days": DEFAULT_WINDOW_DAYS, "costs": {},
                    "coverage": dict(EMPTY_COVERAGE), "source": "none"}

        costs: Dict[str, float] = {}
        cubiertas: Set[str] = set()
        window_days = DEFAULT_WINDOW_DAYS
        currency = "USD"
        edad_maxima = 0.0

        with self._lock:
            entradas = [
                (clave, guardado, valor)
                for clave, (guardado, valor) in self._cache.items()
                if clave and clave[0] == "by_resource" and isinstance(valor, dict)
            ]

        # De mas reciente a mas antigua, para que un scope refrescado gane sobre
        # uno viejo que cubra la misma suscripcion.
        for clave, guardado, valor in sorted(entradas, key=lambda e: e[1], reverse=True):
            de_la_entrada = {
                str(s).lower() for s in (valor.get("coverage") or {}).get("covered", [])
            }
            utiles = (de_la_entrada & pedidas) - cubiertas
            if not utiles:
                continue
            for resource_id, monto in (valor.get("costs") or {}).items():
                if subscription_of(resource_id) in utiles:
                    costs[resource_id] = monto
            cubiertas |= utiles
            window_days = valor.get("window_days") or window_days
            currency = valor.get("currency") or currency
            edad_maxima = max(edad_maxima, time.time() - guardado)

        faltantes = sorted(pedidas - cubiertas)
        denegadas: List[str] = []
        fallidas: List[str] = []
        origen = "cache" if cubiertas else "none"

        if faltantes and allow_query:
            vivo = self.get_cost_by_resource(faltantes)
            cobertura_viva = vivo.get("coverage") or {}
            nuevas = {str(s).lower() for s in cobertura_viva.get("covered", [])}
            costs.update(vivo.get("costs") or {})
            cubiertas |= nuevas
            denegadas = list(cobertura_viva.get("denied", []))
            fallidas = list(cobertura_viva.get("failed", []))
            window_days = vivo.get("window_days") or window_days
            currency = vivo.get("currency") or currency
            origen = "mixto" if origen == "cache" else "live"
        elif faltantes:
            fallidas = faltantes

        cobertura = {
            "covered": sorted(cubiertas),
            "denied": denegadas,
            "failed": [s for s in fallidas if s not in cubiertas],
        }
        return {
            "status": self._coverage_status(cobertura),
            "currency": currency,
            "window_days": window_days,
            "costs": costs,
            "coverage": cobertura,
            "source": origen,
            "cache_age_seconds": round(edad_maxima) if edad_maxima else 0,
        }

    def get_daily_costs(
        self,
        subscription_ids: List[str],
        days: int = DEFAULT_WINDOW_DAYS,
        pace_seconds: float = 0.0,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Serie diaria de gasto real, base para la deteccion de anomalias.

        Devuelve `{"status", "currency", "series", "coverage"}`.
        """
        subscription_ids = [s for s in (subscription_ids or []) if s]
        if not subscription_ids:
            return {"status": "no_subscriptions", "currency": "USD",
                    "series": {}, "coverage": dict(EMPTY_COVERAGE)}

        cache_key = ("daily", tuple(sorted(subscription_ids)), days)
        if not force:
            cached = self._get_cached(cache_key)
            if cached is not None:
                return cached

        token = self._token()
        if not token:
            return {"status": "offline", "currency": "USD",
                    "series": {}, "coverage": dict(EMPTY_COVERAGE)}

        results, coverage = self._run_per_subscription(
            subscription_ids,
            lambda sub_id, tok: self._query_grouped(
                sub_id, None, days, tok, granularity="Daily"
            ),
            token,
            pace_seconds,
        )

        series: Dict[str, float] = {}
        currency = "USD"
        for sub_id in coverage["covered"]:
            result = results[sub_id]
            columns = result.get("columns", [])
            cost_idx = self._cost_index(columns)
            date_idx = self._index_of(columns, "UsageDate")
            currency_idx = self._index_of(columns, "Currency")
            if cost_idx is None or date_idx is None:
                continue
            for row in result.get("rows", []):
                try:
                    # UsageDate llega como entero YYYYMMDD.
                    raw_date = str(row[date_idx])
                    iso_date = f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
                    series[iso_date] = series.get(iso_date, 0.0) + float(row[cost_idx] or 0.0)
                    if currency_idx is not None and row[currency_idx]:
                        currency = str(row[currency_idx])
                except (IndexError, TypeError, ValueError):
                    continue

        payload = {
            "status": self._coverage_status(coverage),
            "currency": currency,
            "series": dict(sorted(series.items())),
            "coverage": coverage,
        }

        if coverage["covered"]:
            self._set_cached(cache_key, payload)
            return payload

        if payload["status"] != "unauthorized":
            stale = self._get_stale(cache_key)
            if stale is not None:
                return {**stale, "stale": True}
        return payload

    def get_daily_cost_by_resource(
        self,
        subscription_ids: List[str],
        days: int = DEFAULT_WINDOW_DAYS,
        pace_seconds: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Gasto real por dia, recurso y servicio: lo que guarda el recolector.

        Sin cache: el recolector corre una vez al dia y necesita el dato fresco.
        Devuelve `{"status", "rows", "coverage"}`, con una fila por
        (suscripcion, dia, recurso, servicio). Los cargos sin recurso (soporte,
        marketplace) llegan con `resource_id` vacio.
        """
        subscription_ids = [s for s in (subscription_ids or []) if s]
        if not subscription_ids:
            return {"status": "no_subscriptions", "rows": [], "coverage": dict(EMPTY_COVERAGE)}
        token = self._token()
        if not token:
            return {"status": "offline", "rows": [], "coverage": dict(EMPTY_COVERAGE)}

        results, coverage = self._run_per_subscription(
            subscription_ids,
            lambda sub_id, tok: self._query_grouped(
                sub_id,
                [{"type": "Dimension", "name": "ResourceId"}, {"type": "Dimension", "name": "ServiceName"}],
                days, tok, granularity="Daily",
            ),
            token,
            pace_seconds,
        )

        filas: List[Dict[str, Any]] = []
        for sub_id in coverage["covered"]:
            result = results[sub_id]
            columns = result.get("columns", [])
            cost_idx = self._cost_index(columns)
            date_idx = self._index_of(columns, "UsageDate")
            res_idx = self._index_of(columns, "ResourceId")
            svc_idx = self._index_of(columns, "ServiceName")
            cur_idx = self._index_of(columns, "Currency")
            if cost_idx is None or date_idx is None:
                continue
            for row in result.get("rows", []):
                try:
                    raw_date = str(row[date_idx])
                    filas.append({
                        "subscription_id": sub_id,
                        "date": f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}",
                        "resource_id": str(row[res_idx] or "").lower() if res_idx is not None else "",
                        "service_name": str(row[svc_idx] or "") if svc_idx is not None else "",
                        "cost": float(row[cost_idx] or 0.0),
                        "currency": str(row[cur_idx]) if cur_idx is not None and row[cur_idx] else "USD",
                    })
                except (IndexError, TypeError, ValueError):
                    continue

        return {"status": self._coverage_status(coverage), "rows": filas, "coverage": coverage}

    def cache_freshness(self, subscription_ids: List[str]) -> Dict[str, Any]:
        """
        Cuanto le queda de vigencia al gasto ya cacheado de este scope.

        Existe para que la precarga no vuelva a consultar Cost Management en
        cada arranque. Con la cache en memoria eso era inevitable —un reinicio
        la vaciaba—, pero ahora sobrevive en disco: cuatro despliegues seguidos
        gastaban cuatro precargas completas contra una API que corta con 429, y
        la cobertura del tenant cayo de 24 suscripciones a 9.

        Devuelve la edad de la entrada, los segundos que le quedan de TTL y si
        conviene refrescar.
        """
        subs = [s for s in (subscription_ids or []) if s]
        clave = ("by_resource", tuple(sorted(subs)), DEFAULT_WINDOW_DAYS)
        with self._lock:
            entrada = self._cache.get(clave)

        if not entrada:
            return {"cached": False, "age_seconds": None,
                    "remaining_seconds": 0, "should_warm": True, "covered": 0}

        edad = time.time() - entrada[0]
        restante = max(0.0, self._ttl - edad)
        cobertura = (entrada[1] or {}).get("coverage") or {}
        return {
            "cached": True,
            "age_seconds": round(edad),
            "remaining_seconds": round(restante),
            "should_warm": restante <= 0,
            "covered": len(cobertura.get("covered", [])),
        }

    def warm(self, subscription_ids: List[str], pace_seconds: float = 0.0) -> Dict[str, Any]:
        """
        Precarga la cache de costos consultando con calma.

        Cost Management consolida el gasto una vez al dia, asi que no tiene
        sentido consultarlo cuando el usuario abre el panel: son ~2 llamadas por
        suscripcion y con casi treinta suscripciones la cuota se agota antes de
        terminar. Al precargar en segundo plano, las peticiones interactivas
        siempre encuentran el dato en cache y nunca esperan a la API.

        Al terminar se reintentan las suscripciones que fallaron por limite de
        tasa. Sin ese reintento se quedaban seis horas sin dato —hasta el
        siguiente ciclo— y el panel las mostraba como estimadas pese a tener
        permisos de costo sobre ellas.
        """
        pace = pace_seconds or WARM_PACE_SECONDS
        inicio = time.time()

        por_recurso = self.get_cost_by_resource(subscription_ids, pace_seconds=pace, force=True)
        diario = self.get_daily_costs(subscription_ids, pace_seconds=pace, force=True)

        recuperadas = 0
        fallidas = sorted(
            set(por_recurso.get("coverage", {}).get("failed", []))
            | set(diario.get("coverage", {}).get("failed", []))
        )
        if fallidas and WARM_RETRY_ENABLED:
            # El 429 significa que la cuota estaba agotada, no que falten
            # permisos: se le da tiempo a que se libere antes de volver.
            print(f"[CostService] Reintentando {len(fallidas)} suscripcion(es) que fallaron.")
            time.sleep(WARM_RETRY_BACKOFF_SECONDS)
            por_recurso, diario, recuperadas = self._segunda_pasada(
                subscription_ids, fallidas, pace * WARM_RETRY_PACE_FACTOR, por_recurso, diario
            )

        cobertura = por_recurso.get("coverage", {})
        return {
            "elapsed_seconds": round(time.time() - inicio, 1),
            "cost_status": por_recurso.get("status"),
            "daily_status": diario.get("status"),
            "covered": len(cobertura.get("covered", [])),
            "denied": len(cobertura.get("denied", [])),
            "failed": len(cobertura.get("failed", [])),
            "recovered_on_retry": recuperadas,
            "pace_seconds": pace,
        }

    # ------------------------------------------------------------------
    # Segunda pasada de la precarga
    # ------------------------------------------------------------------

    def _segunda_pasada(
        self,
        scope: List[str],
        fallidas: List[str],
        pace: float,
        por_recurso: Dict[str, Any],
        diario: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], int]:
        """
        Reconsulta solo las suscripciones que fallaron y fusiona lo recuperado.

        La consulta se hace sobre el sub-scope de las fallidas, pero el
        resultado se escribe en la entrada de cache del scope completo: es la
        que lee el panel, y una entrada aparte para las fallidas no le serviria
        de nada.
        """
        recuperado_r = self.get_cost_by_resource(fallidas, pace_seconds=pace, force=True)
        recuperado_d = self.get_daily_costs(fallidas, pace_seconds=pace, force=True)

        nuevas = self._nuevas_cubiertas(por_recurso, recuperado_r)
        if nuevas:
            por_recurso = self._fusionar_por_recurso(scope, por_recurso, recuperado_r)
        if self._nuevas_cubiertas(diario, recuperado_d):
            diario = self._fusionar_diario(scope, diario, recuperado_d)

        return por_recurso, diario, len(nuevas)

    @staticmethod
    def _nuevas_cubiertas(base: Dict[str, Any], extra: Dict[str, Any]) -> List[str]:
        """
        Suscripciones que el reintento cubrio y la primera pasada no.

        Se comprueba contra la cobertura de `base` —y no contra la lista de
        fallidas— porque `base` puede ser una respuesta servida de cache
        vencida, en cuyo caso ya trae el gasto de esas suscripciones y sumarlo
        otra vez lo duplicaria.
        """
        ya = {str(s).lower() for s in (base.get("coverage") or {}).get("covered", [])}
        return [s for s in (extra.get("coverage") or {}).get("covered", []) if str(s).lower() not in ya]

    @staticmethod
    def _fusionar_cobertura(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, List[str]]:
        """Une dos coberturas; lo resuelto en el reintento sale de 'failed'."""
        base = base or dict(EMPTY_COVERAGE)
        extra = extra or dict(EMPTY_COVERAGE)
        cubiertas = list(dict.fromkeys(base.get("covered", []) + extra.get("covered", [])))
        denegadas = list(dict.fromkeys(base.get("denied", []) + extra.get("denied", [])))
        resueltas = set(cubiertas) | set(denegadas)
        fallidas = [
            s for s in dict.fromkeys(base.get("failed", []) + extra.get("failed", []))
            if s not in resueltas
        ]
        return {"covered": cubiertas, "denied": denegadas, "failed": fallidas}

    def _fusionar_por_recurso(
        self, scope: List[str], base: Dict[str, Any], extra: Dict[str, Any]
    ) -> Dict[str, Any]:
        costs = dict(base.get("costs") or {})
        costs.update(extra.get("costs") or {})
        cobertura = self._fusionar_cobertura(base.get("coverage"), extra.get("coverage"))
        fusionado = {
            **base,
            "costs": costs,
            "coverage": cobertura,
            "status": self._coverage_status(cobertura),
        }
        fusionado.pop("stale", None)
        self._set_cached(("by_resource", tuple(sorted(scope)), DEFAULT_WINDOW_DAYS), fusionado)
        return fusionado

    def _fusionar_diario(
        self, scope: List[str], base: Dict[str, Any], extra: Dict[str, Any]
    ) -> Dict[str, Any]:
        series = dict(base.get("series") or {})
        for fecha, monto in (extra.get("series") or {}).items():
            series[fecha] = round(series.get(fecha, 0.0) + float(monto or 0.0), 2)
        cobertura = self._fusionar_cobertura(base.get("coverage"), extra.get("coverage"))
        fusionado = {
            **base,
            "series": dict(sorted(series.items())),
            "coverage": cobertura,
            "status": self._coverage_status(cobertura),
        }
        fusionado.pop("stale", None)
        self._set_cached(("daily", tuple(sorted(scope)), DEFAULT_WINDOW_DAYS), fusionado)
        return fusionado

    def get_budgets(self, subscription_ids: List[str]) -> Dict[str, Any]:
        """
        Presupuestos definidos realmente en Azure (Consumption Budgets API).

        Antes esta seccion se inventaba: se tomaba el gasto estimado, se le
        sumaba 20% y se reportaba siempre un 83.3% de consumo. Aqui se leen los
        presupuestos que el equipo haya configurado en el portal, con su gasto
        acumulado real. Si no hay ninguno definido la lista viene vacia y la
        interfaz debe invitar a crearlos en lugar de mostrar cifras ficticias.
        """
        subscription_ids = [s for s in (subscription_ids or []) if s]
        if not subscription_ids:
            return {"status": "no_subscriptions", "budgets": [],
                    "coverage": dict(EMPTY_COVERAGE)}

        cache_key = ("budgets", tuple(sorted(subscription_ids)))
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        token = self._token()
        if not token:
            return {"status": "offline", "budgets": [], "coverage": dict(EMPTY_COVERAGE)}

        def fetch(subscription_id: str, tok: str) -> Dict[str, Any]:
            url = (
                f"{MANAGEMENT_ROOT}/subscriptions/{subscription_id}"
                "/providers/Microsoft.Consumption/budgets?api-version=2023-05-01"
            )
            try:
                response = requests.get(
                    url, headers={"Authorization": f"Bearer {tok}"}, timeout=REQUEST_TIMEOUT
                )
            except requests.RequestException as exc:
                return {"status": "error", "message": str(exc), "value": []}

            if response.status_code in (401, 403):
                return {"status": "unauthorized", "message": "Sin permisos", "value": []}
            if response.status_code != 200:
                return {
                    "status": "error",
                    "message": f"HTTP {response.status_code}",
                    "value": [],
                }
            return {"status": "success", "value": response.json().get("value", []) or []}

        results, coverage = self._run_per_subscription(subscription_ids, fetch, token)

        budgets: List[Dict[str, Any]] = []
        for sub_id in coverage["covered"]:
            for item in results[sub_id].get("value", []):
                props = item.get("properties", {}) or {}
                amount = float(props.get("amount") or 0.0)
                current = float((props.get("currentSpend") or {}).get("amount") or 0.0)
                forecast = float((props.get("forecastSpend") or {}).get("amount") or 0.0)
                budgets.append(
                    {
                        "name": item.get("name"),
                        "scope": f"/subscriptions/{sub_id}",
                        "subscriptionId": sub_id,
                        "time_grain": props.get("timeGrain"),
                        "budget_limit": round(amount, 2),
                        "current_spending": round(current, 2),
                        "forecast_spending": round(forecast, 2),
                        "percentage_used": round((current / amount) * 100.0, 1) if amount else 0.0,
                        "currency": (props.get("currentSpend") or {}).get("unit", "USD"),
                    }
                )

        payload = {
            "status": self._coverage_status(coverage),
            "budgets": budgets,
            "coverage": coverage,
        }
        if coverage["covered"]:
            self._set_cached(cache_key, payload)
        return payload

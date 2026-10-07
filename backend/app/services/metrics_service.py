"""
MetricsService — Utilizacion real desde Azure Monitor.

Sustituye la metrica de CPU simulada que devolvia el reporte de FinOps
(`avg_cpu_percentage: 2.4  # Mock monitoring CPU metric`) por el promedio real
de "Percentage CPU" de cada maquina virtual, leido de la Monitor Metrics API.

El rol Reader del Service Principal es suficiente para leer metricas, asi que no
requiere permisos adicionales a los que ya tiene la plataforma.
"""

import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

MANAGEMENT_ROOT = "https://management.azure.com"
METRICS_API_VERSION = "2018-01-01"

DEFAULT_TTL_SECONDS = int(os.getenv("METRICS_CACHE_TTL_SECONDS", "3600"))
REQUEST_TIMEOUT = float(os.getenv("METRICS_REQUEST_TIMEOUT", "20"))

# Numero de recursos que se consultan en paralelo. Monitor tolera bien la
# concurrencia moderada; subirlo mucho provoca 429.
MAX_WORKERS = int(os.getenv("METRICS_MAX_WORKERS", "8"))


class MetricsService:
    """Lee metricas de utilizacion reales de Azure Monitor, con cache."""

    def __init__(self, azure):
        self.azure = azure
        self._cache: Dict[Any, Any] = {}
        self._lock = threading.Lock()
        self._ttl = DEFAULT_TTL_SECONDS

    def _token(self) -> Optional[str]:
        if not getattr(self.azure, "azure_connected", False):
            return None
        credentials = getattr(self.azure, "azure_credentials", None)
        if not credentials:
            return None
        try:
            return credentials.get_token(f"{MANAGEMENT_ROOT}/.default").token
        except Exception as exc:  # pragma: no cover - depende del entorno Azure
            print(f"[MetricsService] No se pudo obtener token de ARM: {exc}")
            return None

    def _fetch_metric(
        self,
        resource_id: str,
        metric_name: str,
        days: int,
        token: str,
    ) -> Optional[float]:
        """Promedio de una metrica en la ventana indicada, o None si no hay datos."""
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        timespan = f"{start.isoformat()}/{end.isoformat()}"

        url = f"{MANAGEMENT_ROOT}{resource_id}/providers/microsoft.insights/metrics"
        params = {
            "api-version": METRICS_API_VERSION,
            "metricnames": metric_name,
            "timespan": timespan,
            "interval": "P1D",
            "aggregation": "average",
        }
        headers = {"Authorization": f"Bearer {token}"}

        try:
            response = requests.get(
                url, headers=headers, params=params, timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException:
            return None

        if response.status_code != 200:
            return None

        try:
            values = response.json().get("value", [])
            if not values:
                return None
            timeseries = values[0].get("timeseries", []) or []
            if not timeseries:
                return None
            points = [
                point.get("average")
                for point in (timeseries[0].get("data", []) or [])
                if point.get("average") is not None
            ]
            if not points:
                return None
            return round(sum(points) / len(points), 2)
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    def get_average_cpu(
        self, resource_ids: List[str], days: int = 30
    ) -> Dict[str, Optional[float]]:
        """
        Promedio de CPU (%) de varias VMs en paralelo.

        Devuelve `{resource_id_en_minusculas: porcentaje}`. Un valor None
        significa que Azure Monitor no tiene datos para ese recurso (VM apagada
        o recien creada), y quien consuma el dato debe distinguir ese caso de un
        cero real en lugar de asumir baja utilizacion.
        """
        resource_ids = [r for r in (resource_ids or []) if r]
        if not resource_ids:
            return {}

        token = self._token()
        if not token:
            return {rid.lower(): None for rid in resource_ids}

        results: Dict[str, Optional[float]] = {}
        pending: List[str] = []
        now = time.time()

        with self._lock:
            for rid in resource_ids:
                entry = self._cache.get((rid.lower(), days))
                if entry and (now - entry[0]) < self._ttl:
                    results[rid.lower()] = entry[1]
                else:
                    pending.append(rid)

        if pending:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(
                        self._fetch_metric, rid, "Percentage CPU", days, token
                    ): rid
                    for rid in pending
                }
                for future in as_completed(futures):
                    rid = futures[future]
                    try:
                        value = future.result()
                    except Exception:
                        value = None
                    results[rid.lower()] = value
                    with self._lock:
                        self._cache[(rid.lower(), days)] = (time.time(), value)

        return results

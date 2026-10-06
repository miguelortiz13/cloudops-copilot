"""
HistoryService — Serie historica de los KPIs de gobernanza.

El pipeline semanal ya genera snapshots, pero son copias completas del Excel:
pesadas de abrir y pensadas para auditoria, no para dibujar una tendencia. El
panel, en consecuencia, solo sabe responder "como esta el inventario hoy" y no
"mejoro el cumplimiento de tags este mes", que es la pregunta que permite saber
si el trabajo de gobernanza esta rindiendo.

Este servicio mantiene un registro append-only muy liviano: una linea JSON por
dia y por scope de suscripciones. A razon de unos 300 bytes por linea, un ano de
historia diaria ocupa alrededor de 110 KB.

Se guarda en el Azure File Share que ya esta montado para el Excel
(`EXCEL_STORAGE_DIR`), de modo que sobrevive a los reinicios del contenedor sin
crear ningun recurso nuevo en Azure ni aumentar el costo. Si esa ruta no esta
disponible se cae a un directorio local, y si tampoco se puede escribir el
servicio simplemente no registra: la tendencia es un extra y nunca debe tumbar
al inventario.

La historia empieza a acumularse desde la primera ejecucion; no reconstruye el
pasado. Los snapshots de Excel existentes podrian sembrarla mas adelante.
"""

import hashlib
import json
import logging

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core import config

logger = logging.getLogger(__name__)

# KPIs que se registran. Se guarda solo lo que dibuja la tendencia, no el
# resumen completo, para que el archivo se mantenga pequeno y legible.
TRACKED_FIELDS = [
    "totalResources",
    "nonCompliantResources",
    "tagCompliancePercentage",
    "shadowItCandidates",
    "resourcesWithoutOwnerCandidate",
    "productionResources",
    "nonProductionResources",
]

MAX_POINTS_RETURNED = 365


class HistoryService:
    """Registra y consulta la evolucion diaria de los KPIs de inventario."""

    def __init__(self, base_dir: Optional[Path] = None):
        self._lock = threading.Lock()
        self._dir = self._resolve_dir(base_dir)

    @staticmethod
    def _resolve_dir(base_dir: Optional[Path]) -> Optional[Path]:
        """
        Elige donde vive el historico.

        Se prefiere el File Share persistente; sin el, un directorio local que al
        menos sirve en desarrollo.
        """
        candidates = []
        if base_dir:
            candidates.append(Path(base_dir))
        # DATA_DIR (antes EXCEL_STORAGE_DIR): File Share en Azure, backend/data en local.
        candidates.append(config.DATA_DIR / "kpi_history")

        for candidate in candidates:
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
            except Exception as exc:
                logger.warning(f"[HistoryService] No se pudo usar {candidate}: {exc}")
        logger.warning("[HistoryService] Sin almacenamiento disponible; no se registrara historia.")
        return None

    @staticmethod
    def _scope_key(subscription_ids: List[str]) -> str:
        """
        Identificador estable del scope consultado.

        La tendencia solo es comparable dentro del mismo conjunto de
        suscripciones: mezclar scopes distintos en una sola serie produciria
        saltos que parecen cambios reales del inventario.
        """
        ids = sorted(s.lower() for s in (subscription_ids or []) if s)
        if not ids:
            return "sin-scope"
        return hashlib.md5(",".join(ids).encode()).hexdigest()[:12]

    def _file_for(self, subscription_ids: List[str]) -> Optional[Path]:
        if self._dir is None:
            return None
        return self._dir / f"kpis_{self._scope_key(subscription_ids)}.jsonl"

    def record(self, subscription_ids: List[str], summary: Dict[str, Any]) -> bool:
        """
        Registra el punto de hoy si aun no existe.

        Devuelve True si se escribio. Se guarda a lo sumo un punto por dia: el
        resumen se consulta muchas veces al dia y la tendencia solo necesita la
        foto diaria.
        """
        path = self._file_for(subscription_ids)
        if path is None or not summary:
            return False

        today = datetime.now(timezone.utc).date().isoformat()
        point = {"date": today, "recordedAt": datetime.now(timezone.utc).isoformat()}
        for field in TRACKED_FIELDS:
            value = summary.get(field)
            if value is not None:
                point[field] = value

        try:
            with self._lock:
                if path.exists():
                    # Se relee la ultima linea en vez de mantener estado en
                    # memoria, porque el proceso se reinicia con frecuencia.
                    last = None
                    with open(path, "r", encoding="utf-8") as fh:
                        for line in fh:
                            line = line.strip()
                            if line:
                                last = line
                    if last:
                        try:
                            if json.loads(last).get("date") == today:
                                return False
                        except json.JSONDecodeError:
                            pass

                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(point, ensure_ascii=False) + "\n")
            return True
        except Exception as exc:
            # Nunca se propaga: la tendencia no puede romper el inventario.
            logger.warning(f"[HistoryService] No se pudo registrar el punto: {exc}")
            return False

    def get_series(self, subscription_ids: List[str], days: int = 90) -> Dict[str, Any]:
        """
        Serie historica del scope, ordenada por fecha.

        Devuelve tambien el delta entre el primer y el ultimo punto, que es lo
        que responde "¿mejoro o empeoro?" sin que la interfaz tenga que
        calcularlo.
        """
        path = self._file_for(subscription_ids)
        empty = {"points": [], "available": False, "deltas": {}, "trackedFields": TRACKED_FIELDS}
        if path is None or not path.exists():
            return empty

        points: List[Dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        points.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:
            logger.warning(f"[HistoryService] No se pudo leer el historico: {exc}")
            return empty

        points.sort(key=lambda p: p.get("date", ""))
        if days:
            points = points[-min(days, MAX_POINTS_RETURNED):]

        deltas: Dict[str, Any] = {}
        if len(points) >= 2:
            primero, ultimo = points[0], points[-1]
            for field in TRACKED_FIELDS:
                a, b = primero.get(field), ultimo.get(field)
                if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                    deltas[field] = round(b - a, 2)

        return {
            "points": points,
            "available": len(points) >= 2,
            "pointCount": len(points),
            "firstDate": points[0].get("date") if points else None,
            "lastDate": points[-1].get("date") if points else None,
            "deltas": deltas,
            "trackedFields": TRACKED_FIELDS,
        }

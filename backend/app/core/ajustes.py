"""
Ajustes de incidentes y de Kubernetes, y silencios, que cambia un usuario en el panel.

Viven en DATA_DIR/ajustes.json (el File Share que comparten el API y los jobs),
no en la base: `k8s-watch` corre cada 10 minutos y abrir la base serverless la
despertaría siempre. Un solo escritor (el API), con reemplazo atómico.
"""

import json
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.core import config

SEVERIDADES = ["critica", "alta", "media"]
INCIDENTES = {
    "ventana_tormenta_seg": 120,  # incidentes del mismo clúster tan juntos se tratan como uno
    "umbral_tormenta": 3,
    "foto_vieja_min": 15,
    "diagnosticar": SEVERIDADES,  # severidades que diagnostica el agente
    "avisar": SEVERIDADES,  # severidades que se publican en el canal
    "postmortem": True,  # borrador al resolverse
    "max_diagnosticos_hora": 0,  # 0: el tope general del modelo (LLM_MAX_REQUESTS_PER_HOUR)
}
CLUSTER = {"namespaces_ignorados": [], "reinicios": 5, "gracia_min": 10, "avisar": True, "avisar_severidades": ["critica", "alta"]}
# Validación: (tipo, mínimo, máximo) para números; listas de severidades; booleanos.
LIMITES = {"ventana_tormenta_seg": (30, 3600), "umbral_tormenta": (2, 50), "foto_vieja_min": (5, 1440),
           "max_diagnosticos_hora": (0, 500), "reinicios": (1, 100), "gracia_min": (1, 120)}
MAX_SILENCIO = timedelta(days=30)
_lock = threading.Lock()


def _ruta():
    return config.DATA_DIR / "ajustes.json"


def _leer() -> Dict[str, Any]:
    try:
        return json.loads(_ruta().read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _escribir(datos: Dict[str, Any]) -> None:
    ruta = _ruta()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=1))
    temporal.replace(ruta)


def validar(base: Dict[str, Any], cambios: Dict[str, Any]) -> Dict[str, Any]:
    """Los cambios sobre `base` con sus tipos y rangos, o ValueError."""
    salida = dict(base)
    for k, v in cambios.items():
        if k not in base:
            raise ValueError(f"Ajuste desconocido: {k}.")
        actual = base[k]
        if isinstance(actual, bool):
            if not isinstance(v, bool):
                raise ValueError(f"{k} debe ser verdadero o falso.")
        elif isinstance(actual, int):
            minimo, maximo = LIMITES[k]
            if not isinstance(v, int) or isinstance(v, bool) or not minimo <= v <= maximo:
                raise ValueError(f"{k} debe ser un entero entre {minimo} y {maximo}.")
        elif k == "namespaces_ignorados":
            if not isinstance(v, list) or len(v) > 50 or not all(isinstance(n, str) and 0 < len(n) <= 63 for n in v):
                raise ValueError("namespaces_ignorados: hasta 50 nombres de namespace.")
            v = sorted(set(n.strip() for n in v))
        elif not isinstance(v, list) or not set(v) <= set(SEVERIDADES):
            raise ValueError(f"{k} debe ser una lista de severidades ({', '.join(SEVERIDADES)}).")
        salida[k] = v
    return salida


def incidentes() -> Dict[str, Any]:
    return {**INCIDENTES, **_leer().get("incidentes", {})}


def cluster(nombre: str) -> Dict[str, Any]:
    return {**CLUSTER, **_leer().get("clusters", {}).get(nombre, {})}


def guardar_incidentes(cambios: Dict[str, Any]) -> Dict[str, Any]:
    with _lock:
        datos = _leer()
        datos["incidentes"] = validar(incidentes(), cambios)
        _escribir(datos)
        return datos["incidentes"]


def guardar_cluster(nombre: str, cambios: Dict[str, Any]) -> Dict[str, Any]:
    with _lock:
        datos = _leer()
        datos.setdefault("clusters", {})[nombre] = validar(cluster(nombre), cambios)
        _escribir(datos)
        return datos["clusters"][nombre]


# ---------------------------------------------------------------- silencios

def _vigente(s: Dict[str, Any], ahora: datetime) -> bool:
    return datetime.fromisoformat(s["hasta"]) > ahora


def silencios(ahora: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Los silencios vigentes."""
    ahora = ahora or datetime.now(timezone.utc)
    return [s for s in _leer().get("silencios", []) if _vigente(s, ahora)]


def silenciar(actor: str, horas: float, motivo: str, cluster: Optional[str] = None, namespace: Optional[str] = None,
              alerta: Optional[str] = None, objeto: Optional[str] = None) -> Dict[str, Any]:
    ahora = datetime.now(timezone.utc)
    if not any((cluster, namespace, alerta, objeto)):
        raise ValueError("Un silencio necesita al menos clúster, namespace, alerta u objeto: no se silencia todo.")
    if not 0 < horas * 3600 <= MAX_SILENCIO.total_seconds():
        raise ValueError("La duración va de minutos a 30 días.")
    for campo in (cluster, namespace, alerta, objeto):
        if campo is not None and not 0 < len(campo) <= 200:
            raise ValueError("Cada campo del silencio tiene hasta 200 caracteres.")
    nuevo = {"id": secrets.token_hex(6), "cluster": cluster, "namespace": namespace, "alerta": alerta, "objeto": objeto,
             "motivo": (motivo or "")[:300], "creado_por": actor, "creado": ahora.isoformat(timespec="seconds"),
             "hasta": (ahora + timedelta(hours=horas)).isoformat(timespec="seconds")}
    with _lock:
        datos = _leer()
        # Los vencidos se limpian al escribir.
        datos["silencios"] = [s for s in datos.get("silencios", []) if _vigente(s, ahora)] + [nuevo]
        _escribir(datos)
    return nuevo


def quitar_silencio(silencio_id: str) -> bool:
    with _lock:
        datos = _leer()
        antes = datos.get("silencios", [])
        datos["silencios"] = [s for s in antes if s["id"] != silencio_id]
        _escribir(datos)
        return len(datos["silencios"]) < len(antes)


def silenciado(lista: List[Dict[str, Any]], cluster: Optional[str], namespace: Optional[str],
               alerta: Optional[str], objetos: List[str]) -> Optional[Dict[str, Any]]:
    """El primer silencio que cubre algo con esas propiedades. `objeto` coincide si está contenido en un nombre."""
    for s in lista:
        if ((s["cluster"] is None or s["cluster"] == cluster) and (s["namespace"] is None or s["namespace"] == namespace)
                and (s["alerta"] is None or s["alerta"] == alerta)
                and (s["objeto"] is None or any(s["objeto"] in (o or "") for o in objetos))):
            return s
    return None

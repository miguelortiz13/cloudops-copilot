"""
Ajustes de la plataforma que cambia un administrador en el panel (Plataforma → Ajustes), y silencios.

Un registro con una sección por dominio y su esquema (valor por defecto, tipo, rango). Las
reglas que antes solo eran variables de entorno (tags obligatorias y de showback, presupuestos,
topes del modelo) toman la variable como valor inicial hasta que alguien las guarde aquí.
Cada cambio queda en un historial con el antes y el después, para deshacerlo.

Viven en DATA_DIR/ajustes.json (el File Share que comparten el API y los jobs), no en la base:
`k8s-watch` corre cada 10 minutos y abrir la base serverless la despertaría siempre. Un solo
escritor (el API), con reemplazo atómico.
"""

import json
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core import config

SEVERIDADES = ["critica", "alta", "media"]
NUBES = ("azure", "aws")
MAX_HISTORIAL = 50
MAX_SILENCIO = timedelta(days=30)


def _presupuestos_del_entorno() -> Dict[str, float]:
    """`MONTHLY_BUDGETS_USD="azure=5,aws=5"`: el valor inicial de los presupuestos."""
    import os
    pares = (p.split("=", 1) for p in os.getenv("MONTHLY_BUDGETS_USD", "").split(",") if "=" in p)
    leidos = {n.strip().lower(): float(v) for n, v in pares if v.strip()}
    return {f"presupuesto_{n}_usd": leidos.get(n, 0.0) for n in NUBES}


# Esquema por clave: ("int"|"float", mínimo, máximo) · ("bool",) · ("severidades",) · ("nombres", máx. elementos, ordenar).
ESQUEMA: Dict[str, Tuple] = {
    "ventana_tormenta_seg": ("int", 30, 3600), "umbral_tormenta": ("int", 2, 50), "foto_vieja_min": ("int", 5, 1440),
    "diagnosticar": ("severidades",), "avisar": ("severidades",), "postmortem": ("bool",),
    "max_diagnosticos_hora": ("int", 0, 500),
    "namespaces_ignorados": ("nombres", 50, True), "reinicios": ("int", 1, 100), "gracia_min": ("int", 1, 120),
    "avisar_severidades": ("severidades",),
    "tags_obligatorias": ("nombres", 20, False), "tags_showback": ("nombres", 10, False),
    "presupuesto_azure_usd": ("float", 0, 1_000_000), "presupuesto_aws_usd": ("float", 0, 1_000_000),
    "max_consultas_hora": ("int", 0, 10_000), "max_consultas_dia": ("int", 0, 100_000),
    "modo": ("opcion", "registro", "activo"), "deduplicar_min": ("int", 0, 1440),
}
# En un clúster, `avisar` es sí o no (en incidentes es la lista de severidades que se avisan).
ESQUEMA_CLUSTER = {**ESQUEMA, "avisar": ("bool",)}
LIMITES = {k: (e[1], e[2]) for k, e in ESQUEMA.items() if e[0] in ("int", "float")}

INCIDENTES = {
    "ventana_tormenta_seg": 120,  # incidentes del mismo clúster tan juntos se tratan como uno
    "umbral_tormenta": 3,
    "foto_vieja_min": 15,
    "diagnosticar": SEVERIDADES,  # severidades que diagnostica el agente
    "avisar": SEVERIDADES,  # severidades que se publican en el canal
    "postmortem": True,  # borrador al resolverse
    "max_diagnosticos_hora": 0,  # 0: el tope general del modelo
}
CLUSTER = {"namespaces_ignorados": [], "reinicios": 5, "gracia_min": 10, "avisar": True, "avisar_severidades": ["critica", "alta"]}

# Secciones de Plataforma → Ajustes y sus valores por defecto. Las de variables de entorno se copian al importar:
# después, aplicar_a_config() cambia esas mismas listas de config y no deben arrastrar el defecto.
SECCIONES: Dict[str, Dict[str, Any]] = {
    "incidentes": INCIDENTES,
    "gobierno": {"tags_obligatorias": list(config.MANDATORY_TAGS), "tags_showback": list(config.SHOWBACK_TAGS)},
    "costos": {},  # su valor inicial se lee al usarlo (_defecto): la variable puede cambiar después de importar
    "ia": {"max_consultas_hora": config.LLM_MAX_REQUESTS_PER_HOUR, "max_consultas_dia": config.LLM_MAX_REQUESTS_PER_DAY},
    # Motor de avisos (app/core/avisos.py): en `registro` envía como antes y anota lo que habría silenciado o descartado.
    "avisos": {"modo": "registro", "deduplicar_min": 10},
}
# Las que vienen de variables de entorno: el panel muestra "variable" como origen hasta que se guarden.
DESDE_ENTORNO = {"gobierno", "costos", "ia"}
_NOMBRE = re.compile(r"^[^<>%&\\?/\x00-\x1f]{1,64}$")
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


def _valor(k: str, v: Any, esquema: Dict[str, Tuple]) -> Any:
    tipo = esquema[k]
    if tipo[0] == "bool":
        if not isinstance(v, bool):
            raise ValueError(f"{k} debe ser verdadero o falso.")
        return v
    if tipo[0] in ("int", "float"):
        _, minimo, maximo = tipo
        entero_ok = isinstance(v, int) and not isinstance(v, bool)
        if not (entero_ok or (tipo[0] == "float" and isinstance(v, float))) or not minimo <= v <= maximo:
            raise ValueError(f"{k} debe ser un {'entero' if tipo[0] == 'int' else 'número'} entre {minimo} y {maximo}.")
        return float(v) if tipo[0] == "float" else v
    if tipo[0] == "opcion":
        if v not in tipo[1:]:
            raise ValueError(f"{k} debe ser uno de: {', '.join(tipo[1:])}.")
        return v
    if tipo[0] == "severidades":
        if not isinstance(v, list) or not set(v) <= set(SEVERIDADES):
            raise ValueError(f"{k} debe ser una lista de severidades ({', '.join(SEVERIDADES)}).")
        return [s for s in SEVERIDADES if s in v]
    _, maximo, ordenar = tipo
    if not isinstance(v, list) or len(v) > maximo or not all(isinstance(n, str) and _NOMBRE.match(n.strip()) for n in v):
        raise ValueError(f"{k}: hasta {maximo} nombres de 1 a 64 caracteres, sin < > % & \\ ? /.")
    limpios = list(dict.fromkeys(n.strip() for n in v))
    if k == "tags_obligatorias" and not limpios:
        raise ValueError("tags_obligatorias necesita al menos una tag.")
    return sorted(limpios) if ordenar else limpios


def validar(base: Dict[str, Any], cambios: Dict[str, Any], esquema: Dict[str, Tuple] = ESQUEMA) -> Dict[str, Any]:
    """Los cambios sobre `base` con sus tipos y rangos, o ValueError."""
    salida = dict(base)
    for k, v in cambios.items():
        if k not in base:
            raise ValueError(f"Ajuste desconocido: {k}.")
        salida[k] = _valor(k, v, esquema)
    return salida


def _defecto(nombre: str) -> Dict[str, Any]:
    return _presupuestos_del_entorno() if nombre == "costos" else SECCIONES[nombre]


def seccion(nombre: str) -> Dict[str, Any]:
    return {**_defecto(nombre), **_leer().get(nombre, {})}


def origen(nombre: str) -> str:
    """De dónde sale hoy la sección: `ajuste` (guardada en el panel), `variable` o `defecto`."""
    if nombre in _leer():
        return "ajuste"
    return "variable" if nombre in DESDE_ENTORNO else "defecto"


def _registrar(datos: Dict[str, Any], actor: str, clave: str, antes: Any, despues: Any) -> None:
    entrada = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "actor": actor, "seccion": clave,
               "antes": antes, "despues": despues}
    datos["historial"] = ([entrada] + datos.get("historial", []))[:MAX_HISTORIAL]


def guardar(nombre: str, cambios: Dict[str, Any], actor: str = "sistema") -> Dict[str, Any]:
    with _lock:
        datos = _leer()
        antes = {**_defecto(nombre), **datos.get(nombre, {})}
        datos[nombre] = validar(antes, cambios)
        _registrar(datos, actor, nombre, antes, datos[nombre])
        _escribir(datos)
    aplicar_a_config()
    return datos[nombre]


def historial() -> List[Dict[str, Any]]:
    return _leer().get("historial", [])


def deshacer(indice: int, actor: str) -> Dict[str, Any]:
    """Vuelve la sección de la entrada `indice` del historial a como estaba antes de ese cambio (queda registrado)."""
    entradas = historial()
    if not 0 <= indice < len(entradas):
        raise ValueError("No existe esa entrada del historial.")
    e = entradas[indice]
    if e["seccion"].startswith("cluster:"):
        return guardar_cluster(e["seccion"].split(":", 1)[1], e["antes"], actor)
    return guardar(e["seccion"], e["antes"], actor)


def aplicar_a_config() -> None:
    """
    Lleva gobierno e IA a los valores de config que lee el resto del código: al arrancar el API o un job y al guardar.
    shortcut: cambia las mismas listas de config en su lugar (unos 40 usos las leen); pasar a una función al mudar
    cada dominio (fases 3 a 5).
    """
    g, ia = seccion("gobierno"), seccion("ia")
    config.MANDATORY_TAGS[:] = g["tags_obligatorias"]
    config.SHOWBACK_TAGS[:] = g["tags_showback"]
    config.LLM_MAX_REQUESTS_PER_HOUR, config.LLM_MAX_REQUESTS_PER_DAY = ia["max_consultas_hora"], ia["max_consultas_dia"]


def presupuestos() -> Dict[str, float]:
    """Presupuesto mensual por nube en USD (las que tienen uno mayor que cero)."""
    c = seccion("costos")
    return {n: c[f"presupuesto_{n}_usd"] for n in NUBES if c[f"presupuesto_{n}_usd"] > 0}


def incidentes() -> Dict[str, Any]:
    return seccion("incidentes")


def cluster(nombre: str) -> Dict[str, Any]:
    return {**CLUSTER, **_leer().get("clusters", {}).get(nombre, {})}


def guardar_incidentes(cambios: Dict[str, Any], actor: str = "sistema") -> Dict[str, Any]:
    return guardar("incidentes", cambios, actor)


def guardar_cluster(nombre: str, cambios: Dict[str, Any], actor: str = "sistema") -> Dict[str, Any]:
    with _lock:
        datos = _leer()
        antes = {**CLUSTER, **datos.get("clusters", {}).get(nombre, {})}
        datos.setdefault("clusters", {})[nombre] = validar(antes, cambios, ESQUEMA_CLUSTER)
        _registrar(datos, actor, f"cluster:{nombre}", antes, datos["clusters"][nombre])
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

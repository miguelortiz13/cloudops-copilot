"""
Motor de avisos (fase 2 del plan 10): el único camino por el que la plataforma publica en el canal.

Cada emisor (avisos diarios, k8s-watch, incidentes, reporte mensual, resumen semanal) arma su
mensaje y lo publica aquí con su dominio, tipo, severidad y clave. El motor:

1. aplica los silencios (los mismos de Operación → Silencios) si el aviso dice a qué clúster,
   namespace, alerta u objeto se refiere;
2. descarta un duplicado: la misma clave enviada hace menos de `deduplicar_min`;
3. arma el mensaje del canal (Discord, Slack o Teams; el PDF adjunto solo en Discord) y lo envía;
4. deja cada aviso en el registro (`DATA_DIR/avisos/AAAA-MM.jsonl`), que se ve en Operación → Avisos.

En modo `registro` (Plataforma → Ajustes → Avisos) envía todo como antes y solo anota lo que
habría silenciado o descartado: así se compara una semana antes de pasar a `activo`.
Corre igual en el API y en los jobs, sin abrir la base.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from app.core import ajustes, config

DOMINIOS = ("inicio", "activos", "costos", "riesgo", "operacion", "plataforma")


def _carpeta():
    return config.DATA_DIR / "avisos"


def _anotar(entrada: Dict[str, Any]) -> None:
    # shortcut: un append por línea, sin bloqueo entre procesos (API y jobs rara vez escriben en el mismo segundo);
    # pasar a una tabla si el registro se usa para algo más que mirarlo.
    carpeta = _carpeta()
    carpeta.mkdir(parents=True, exist_ok=True)
    with open(carpeta / f"{entrada['at'][:7]}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entrada, ensure_ascii=False) + "\n")


def registro(dias: int = 30, ahora: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Los avisos de los últimos `dias`, el más reciente primero."""
    ahora = ahora or datetime.now(timezone.utc)
    desde = (ahora - timedelta(days=dias)).isoformat()
    meses = sorted({(ahora - timedelta(days=d)).strftime("%Y-%m") for d in range(0, dias + 1, 28)} | {ahora.strftime("%Y-%m")})
    filas: List[Dict[str, Any]] = []
    for mes in meses:
        try:
            with open(_carpeta() / f"{mes}.jsonl", encoding="utf-8") as f:
                filas += [json.loads(linea) for linea in f if linea.strip()]
        except FileNotFoundError:
            continue
    return sorted((e for e in filas if e["at"] >= desde), key=lambda e: e["at"], reverse=True)


def _duplicado(clave: str, minutos: int, ahora: datetime) -> bool:
    desde = (ahora - timedelta(minutes=minutos)).isoformat()
    return any(e["clave"] == clave and e["enviado"] and e["at"] >= desde for e in registro(1, ahora))


def publicar(url: str, mensaje: Dict[str, Any], *, dominio: str, tipo: str, severidad: str, clave: str,
             color: int = 0xEF4444, atributos: Optional[Dict[str, Any]] = None,
             adjunto: Optional[Tuple[str, bytes, str]] = None, ahora: Optional[datetime] = None) -> str:
    """
    Publica `mensaje` ({titulo, lineas, enlace}) y devuelve la decisión: enviado, silenciado, duplicado.
    Lanza RuntimeError si el canal falla (el emisor decide si reintenta), después de anotarlo.
    `atributos`: cluster, namespace, alerta y objetos, para los silencios.
    """
    from app.collectors import notify

    ahora = ahora or datetime.now(timezone.utc)
    a = ajustes.seccion("avisos")
    activo = a["modo"] == "activo"
    atributos = atributos or {}
    silencio = None
    if atributos:
        silencio = ajustes.silenciado(ajustes.silencios(ahora), atributos.get("cluster"), atributos.get("namespace"),
                                      atributos.get("alerta"), list(atributos.get("objetos") or []))
    decision = "silenciado" if silencio else "duplicado" if _duplicado(clave, a["deduplicar_min"], ahora) else "enviado"
    entrada = {"at": ahora.isoformat(timespec="seconds"), "dominio": dominio, "tipo": tipo, "severidad": severidad,
               "clave": clave[:300], "titulo": str(mensaje.get("titulo", ""))[:250], "enlace": mensaje.get("enlace"),
               "canal": urlparse(url).hostname, "modo": a["modo"], "decision": decision,
               "silencio": silencio["id"] if silencio else None, "enviado": False, "error": None}
    if decision != "enviado" and activo:
        _anotar(entrada)
        return decision
    cuerpo = notify.payload(url, mensaje, color=color)
    try:
        if adjunto and (urlparse(url).hostname or "") in ("discord.com", "discordapp.com"):
            nombre, datos, tipo_mime = adjunto
            notify.enviar(url, data={"payload_json": json.dumps(cuerpo)}, files={"files[0]": (nombre, datos, tipo_mime)})
        else:
            notify.enviar(url, json=cuerpo)
    except RuntimeError as exc:
        entrada["error"] = str(exc)[:300]
        _anotar(entrada)
        raise
    entrada["enviado"] = True
    _anotar(entrada)
    return "enviado"

"""
Chequeos HTTP (fase 4 del plan 10): una fuente de incidentes para lo que no tiene Alertmanager.

k8s-watch revisa cada 10 minutos las URLs de Plataforma → Ajustes → Chequeos. Una URL que falla dos
veces seguidas (sin respuesta, o código 5xx) se publica en el API como una alerta con el formato de
Alertmanager y el mismo token: entra como incidente con diagnóstico, tormentas y avisos. Cuando vuelve
a responder, se publica resuelta. El estado (fallas seguidas, última respuesta) vive en
DATA_DIR/chequeos.json, sin abrir la base.

Las URLs las elige un administrador, pero igual se rechaza lo que resuelve a una dirección privada,
local o de metadatos: el job no es una puerta a la red interna.
"""

import ipaddress
import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from app.core import ajustes, config

FALLAS_PARA_ABRIR = 2
TIMEOUT = 10


def _ruta() -> Path:
    return Path(config.DATA_DIR) / "chequeos.json"


def leer_estado() -> Dict[str, Any]:
    try:
        return json.loads(_ruta().read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _guardar(estado: Dict[str, Any]) -> None:
    ruta = _ruta()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(estado, ensure_ascii=False, indent=1))
    temporal.replace(ruta)


def direccion_publica(host: str) -> bool:
    """True si todas las direcciones del host son públicas (ni privadas, ni locales, ni de metadatos)."""
    try:
        direcciones = {i[4][0] for i in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return False
    return bool(direcciones) and all(ipaddress.ip_address(d.split("%")[0]).is_global for d in direcciones)


def revisar(url: str) -> Dict[str, Any]:
    """Una petición GET: ok si responde por debajo de 500."""
    host = urlparse(url).hostname or ""
    if not direccion_publica(host):
        return {"ok": False, "status": None, "ms": None, "error": "La URL no resuelve a una dirección pública."}
    inicio = time.monotonic()
    try:
        r = requests.get(url, timeout=TIMEOUT, allow_redirects=False, headers={"User-Agent": "CloudOps-Copilot-chequeo"})
    except requests.RequestException as exc:
        return {"ok": False, "status": None, "ms": None, "error": type(exc).__name__}
    ms = int((time.monotonic() - inicio) * 1000)
    return {"ok": r.status_code < 500, "status": r.status_code, "ms": ms, "error": None if r.status_code < 500 else f"HTTP {r.status_code}"}


def _alerta(url: str, resultado: Dict[str, Any], estado: str, ahora: datetime) -> Dict[str, Any]:
    host = urlparse(url).hostname or url
    alerta = {"status": estado, "startsAt": ahora.isoformat(), "endsAt": ahora.isoformat() if estado == "resolved" else "",
              "labels": {"alertname": "HttpCheckFailed", "instance": url[:200], "service": host, "severity": "critical"},
              "annotations": {"summary": f"{host} no responde bien al chequeo HTTP",
                              "description": f"GET {url}: {resultado.get('error') or resultado.get('status')}"}}
    return {"version": "4", "status": estado, "groupKey": f"http:{url}", "alerts": [alerta],
            "commonLabels": {"alertname": "HttpCheckFailed", "service": host}}


def ejecutar(ahora: Optional[datetime] = None, revisar_url=revisar) -> List[Dict[str, Any]]:
    """Revisa las URLs y publica las que abren o cierran. Devuelve el resultado de cada una."""
    ahora = ahora or datetime.now(timezone.utc)
    urls = ajustes.seccion("chequeos")["urls"]
    api, token = os.getenv("API_URL", "").rstrip("/"), os.getenv("ALERTS_INGEST_TOKEN", "")
    previo = leer_estado()
    nuevo: Dict[str, Any] = {}
    for url in urls:
        r = revisar_url(url)
        antes = previo.get(url, {})
        fallas = 0 if r["ok"] else antes.get("fallas", 0) + 1
        abierta = antes.get("abierta", False)
        publicar = None
        if fallas >= FALLAS_PARA_ABRIR and not abierta:
            publicar, abierta = "firing", True
        elif r["ok"] and abierta:
            publicar, abierta = "resolved", False
        if publicar and api and token:
            try:
                requests.post(f"{api}/api/alerts/alertmanager", json=_alerta(url, r, publicar, ahora),
                              headers={"Authorization": f"Bearer {token}"}, timeout=30).raise_for_status()
            except requests.RequestException as exc:
                # Sin publicar, el estado no avanza: la próxima corrida lo intenta de nuevo.
                print(f"[chequeos] No se pudo publicar {url}: {type(exc).__name__}")
                abierta = antes.get("abierta", False)
        nuevo[url] = {**r, "fallas": fallas, "abierta": abierta, "at": ahora.isoformat(timespec="seconds")}
    _guardar(nuevo)
    return [{"url": u, **v} for u, v in nuevo.items()]

"""
Avisos de Kubernetes casi en vivo (docs/plan/08-kubernetes.md, parte 4).

    python -m app.collectors.k8s_watch

Un Container Apps Job lo corre cada 10 minutos (`kubernetes_watch_cron`). Lee la
foto de cada clúster (sin abrir la base), calcula sus incidencias críticas y
altas y avisa al webhook de `NOTIFY_WEBHOOK_URL`:

- una incidencia nueva, cuando aparece en dos fotos seguidas (así no avisa de un
  pod que solo estaba arrancando ni de un despliegue en curso);
- su resolución, cuando deja de aparecer;
- un agente que dejó de reportar (foto de más de 15 minutos), y su regreso.

El estado (qué está abierto y qué ya se avisó) vive en DATA_DIR/k8s_watch.json.
Si el envío falla, el estado no se guarda y la siguiente ejecución lo repite.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.collectors import notify
from app.core import config
from app.services import k8s_fleet

SEVERIDADES = ("critica", "alta")


def _ruta() -> Path:
    return Path(config.DATA_DIR) / "k8s_watch.json"


def leer_estado() -> Dict:
    try:
        return json.loads(_ruta().read_text())
    except FileNotFoundError:
        return {}


def guardar_estado(estado: Dict) -> None:
    ruta = _ruta()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(estado, indent=1))
    temporal.replace(ruta)


def _clave(i: Dict) -> str:
    return f"{i['namespace'] or '-'}/{i['resource']}"


def evaluar(nombre: str, foto: Optional[Dict], previo: Dict, ahora: datetime) -> tuple[Dict, List[str]]:
    """(estado nuevo del clúster, líneas a avisar)."""
    if foto is None:  # el agente nunca reportó: nada que vigilar todavía
        return previo, []
    lineas: List[str] = []
    estado = {"collected_at": foto.get("collected_at"), "abiertas": dict(previo.get("abiertas", {})),
              "pendientes": dict(previo.get("pendientes", {})), "sin_reportar": previo.get("sin_reportar", False)}
    edad = k8s_fleet._segundos(foto.get("collected_at"), ahora)
    if edad is None or edad > k8s_fleet.VIEJA_SEGUNDOS:
        if not estado["sin_reportar"]:
            lineas.append(f"- El agente dejó de reportar: última foto hace {int((edad or 0) // 60)} min")
            estado["sin_reportar"] = True
        # Sin foto nueva no se sabe qué se resolvió: lo abierto queda como estaba.
        return estado, lineas
    if estado["sin_reportar"]:
        lineas.append("- El agente volvió a reportar")
        estado["sin_reportar"] = False
    if previo.get("collected_at") == foto.get("collected_at"):
        return estado, lineas  # misma foto que la vez anterior: no cuenta como "dos seguidas"

    vigentes = {_clave(i): i for i in k8s_fleet.incidencias(foto, ahora) if i["severity"] in SEVERIDADES}
    for clave, i in vigentes.items():
        if clave in estado["abiertas"]:
            continue
        if clave in estado["pendientes"]:
            lineas.append(f"- [{i['severity']}] {i['title']}" + (f" ({i['namespace']})" if i["namespace"] else ""))
            estado["abiertas"][clave] = i["title"]
    for clave, titulo in list(estado["abiertas"].items()):
        if clave not in vigentes:
            lineas.append(f"- Resuelta: {titulo}")
            del estado["abiertas"][clave]
    estado["pendientes"] = {c: i["title"] for c, i in vigentes.items() if c not in estado["abiertas"]}
    return estado, lineas


def ejecutar(credenciales, ahora: Optional[datetime] = None) -> int:
    """Envía lo nuevo y devuelve cuántas líneas avisó."""
    url = os.getenv("NOTIFY_WEBHOOK_URL", "").strip()
    if not url:
        print("[k8s_watch] Sin NOTIFY_WEBHOOK_URL: nada que hacer.")
        return 0
    ahora = ahora or k8s_fleet.ahora()
    estado = leer_estado()
    nuevo, avisos = {}, {}
    for nombre in k8s_fleet.configurados():
        nuevo[nombre], lineas = evaluar(nombre, k8s_fleet.leer(credenciales, nombre), estado.get(nombre, {}), ahora)
        if lineas:
            avisos[nombre] = lineas
    for nombre, lineas in avisos.items():
        m = {"titulo": f"{config.APP_NAME}: Kubernetes · {nombre}", "lineas": lineas,
             "enlace": f"{config.FRONTEND_URL}/#/kubernetes/{nombre}"}
        grave = any(x.startswith(("- [critica]", "- El agente dejó")) for x in lineas)
        resuelto = all(x.startswith(("- Resuelta", "- El agente volvió")) for x in lineas)
        notify.enviar(url, json=notify.payload(url, m, color=0x22C55E if resuelto else 0xEF4444 if grave else 0xF59E0B))
    guardar_estado(nuevo)
    return sum(map(len, avisos.values()))


def main() -> int:
    from azure.identity import DefaultAzureCredential

    credenciales = DefaultAzureCredential(managed_identity_client_id=os.getenv("AZURE_MANAGED_IDENTITY_CLIENT_ID") or None)
    try:
        enviados = ejecutar(credenciales)
    except Exception as exc:  # el job queda en error y la siguiente ejecución reintenta
        print(f"[k8s_watch] error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"[k8s_watch] {enviados} aviso(s) enviados")
    return 0


if __name__ == "__main__":
    sys.exit(main())

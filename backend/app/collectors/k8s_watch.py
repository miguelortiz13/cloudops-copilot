"""
Avisos de Kubernetes casi en vivo (docs/plan/08-kubernetes.md, parte 4).

    python -m app.collectors.k8s_watch

Un Container Apps Job lo corre cada 10 minutos (`kubernetes_watch_cron`). Lee la
foto de cada clúster (sin abrir la base), calcula sus incidencias críticas y
altas y avisa al webhook de `NOTIFY_WEBHOOK_URL`:

- una incidencia nueva, cuando aparece en dos fotos seguidas (así no avisa de un
  pod que solo estaba arrancando ni de un despliegue en curso);
- su resolución, cuando deja de aparecer;
- un agente que dejó de reportar (foto más vieja que `foto_vieja_min`), y su regreso.

Respeta los ajustes del clúster (si avisa y de qué severidades) y los silencios
(app/core/ajustes.py): una incidencia silenciada no se avisa.

El estado (qué está abierto y qué ya se avisó) vive en DATA_DIR/k8s_watch.json. Además lleva la
historia de TODAS las incidencias (también las que no se avisan): cuando una deja de aparecer, su
inicio, fin y duración quedan en DATA_DIR/k8s_historial/<clúster>.jsonl (Activos → Kubernetes).
Si el envío falla, el estado no se guarda y la siguiente ejecución lo repite.
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from app.core import ajustes, avisos, config
from app.services import k8s_fleet


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


def _carpeta_historial() -> Path:
    return Path(config.DATA_DIR) / "k8s_historial"


def anotar_historial(cluster: str, filas: List[Dict]) -> None:
    if not filas:
        return
    carpeta = _carpeta_historial()
    carpeta.mkdir(parents=True, exist_ok=True)
    with open(carpeta / f"{cluster}.jsonl", "a", encoding="utf-8") as f:
        for fila in filas:
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")


def historial(cluster: str, dias: int = 30, ahora: Optional[datetime] = None) -> Dict:
    """Las incidencias cerradas de los últimos `dias` (más reciente primero) y las abiertas ahora, con su duración."""
    ahora = ahora or k8s_fleet.ahora()
    desde = (ahora - timedelta(days=dias)).isoformat()

    def minutos(a: Optional[str], b: Optional[str]) -> Optional[int]:
        if not a or not b:
            return None
        return int((datetime.fromisoformat(b.replace("Z", "+00:00")) - datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds() // 60)

    try:
        with open(_carpeta_historial() / f"{cluster}.jsonl", encoding="utf-8") as f:
            cerradas = [json.loads(linea) for linea in f if linea.strip()]
    except FileNotFoundError:
        cerradas = []
    cerradas = sorted((c | {"minutes": minutos(c["desde"], c["hasta"])} for c in cerradas if (c.get("hasta") or "") >= desde),
                      key=lambda c: c["hasta"], reverse=True)
    abiertas = sorted((h | {"hasta": None, "minutes": minutos(h["desde"], ahora.isoformat())}
                       for h in leer_estado().get(cluster, {}).get("historia", {}).values()), key=lambda h: h["desde"] or "")
    duraciones = sorted(c["minutes"] for c in cerradas if c["minutes"] is not None)
    return {"cluster": cluster, "days": dias, "open": abiertas, "closed": cerradas[:300],
            "median_minutes": duraciones[len(duraciones) // 2] if duraciones else None}


def _clave(i: Dict) -> str:
    return f"{i['namespace'] or '-'}/{i['resource']}"


def evaluar(nombre: str, foto: Optional[Dict], previo: Dict, ahora: datetime) -> tuple[Dict, List[str]]:
    """(estado nuevo del clúster, líneas a avisar)."""
    if foto is None:  # el agente nunca reportó: nada que vigilar todavía
        return previo, []
    lineas: List[str] = []
    estado = {"collected_at": foto.get("collected_at"), "abiertas": dict(previo.get("abiertas", {})),
              "pendientes": dict(previo.get("pendientes", {})), "sin_reportar": previo.get("sin_reportar", False),
              "historia": dict(previo.get("historia", {}))}
    edad = k8s_fleet._segundos(foto.get("collected_at"), ahora)
    if edad is None or edad > k8s_fleet.vieja_segundos():
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

    a = ajustes.cluster(nombre)
    todas = {_clave(i): i for i in k8s_fleet.incidencias(foto, ahora, nombre)}
    # Historia: lo que aparece se abre con la hora de la foto; lo que ya no está se cierra (ejecutar() lo anota).
    momento = foto.get("collected_at")
    for clave, i in todas.items():
        estado["historia"].setdefault(clave, {k: i[k] for k in ("title", "severity", "category", "namespace", "resource")}
                                      | {"desde": momento})
    estado["cerradas"] = [estado["historia"].pop(c) | {"hasta": momento} for c in list(estado["historia"]) if c not in todas]
    vigentes = {c: i for c, i in todas.items()
                if a["avisar"] and i["severity"] in a["avisar_severidades"] and not i["silenced_until"]}
    for clave, i in vigentes.items():
        if clave in estado["abiertas"]:
            continue
        if clave in estado["pendientes"]:
            lineas.append(f"- [{i['severity']}] {i['title']}" + (f" ({i['namespace']})" if i["namespace"] else ""))
            estado["abiertas"][clave] = i["title"]
    for clave, titulo in list(estado["abiertas"].items()):
        if clave not in vigentes:
            if clave not in todas:  # si sigue ahí pero se silenció o dejó de avisarse, sale sin "Resuelta"
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
    nuevo, por_cluster = {}, {}
    cerradas: Dict[str, List[Dict]] = {}
    for nombre in k8s_fleet.configurados():
        nuevo[nombre], lineas = evaluar(nombre, k8s_fleet.leer(credenciales, nombre), estado.get(nombre, {}), ahora)
        cerradas[nombre] = nuevo[nombre].pop("cerradas", [])
        if lineas:
            por_cluster[nombre] = lineas
    for nombre, lineas in por_cluster.items():
        m = {"titulo": f"{config.APP_NAME}: Kubernetes · {nombre}", "lineas": lineas,
             "enlace": f"{config.FRONTEND_URL}/#/activos/kubernetes/{nombre}"}
        grave = any(x.startswith(("- [critica]", "- El agente dejó")) for x in lineas)
        resuelto = all(x.startswith(("- Resuelta", "- El agente volvió")) for x in lineas)
        avisos.publicar(url, m, dominio="activos", tipo="kubernetes", severidad="critica" if grave else "alta",
                        clave=f"k8s:{nombre}:{hashlib.sha1(chr(10).join(lineas).encode()).hexdigest()[:12]}", atributos={"cluster": nombre},
                        color=0x22C55E if resuelto else 0xEF4444 if grave else 0xF59E0B)
    for nombre, filas in cerradas.items():
        anotar_historial(nombre, filas)
    guardar_estado(nuevo)
    return sum(map(len, por_cluster.values()))


def main() -> int:
    from azure.identity import DefaultAzureCredential

    credenciales = DefaultAzureCredential(managed_identity_client_id=os.getenv("AZURE_MANAGED_IDENTITY_CLIENT_ID") or None)
    try:
        from app.collectors import chequeos
        revisadas = chequeos.ejecutar()
        print(f"[chequeos] {sum(1 for r in revisadas if r['ok'])} de {len(revisadas)} URL(s) responden")
    except Exception as exc:  # los chequeos no frenan la vigilancia de Kubernetes
        print(f"[chequeos] error: {type(exc).__name__}: {exc}", file=sys.stderr)
    try:
        enviados = ejecutar(credenciales)
    except Exception as exc:  # el job queda en error y la siguiente ejecución reintenta
        print(f"[k8s_watch] error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"[k8s_watch] {enviados} aviso(s) enviados")
    return 0


if __name__ == "__main__":
    sys.exit(main())

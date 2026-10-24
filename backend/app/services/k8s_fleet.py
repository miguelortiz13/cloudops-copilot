"""
Clústeres de Kubernetes desde las fotos que suben sus agentes (docs/plan/08-kubernetes.md).

Cada agente deja `k8s-<clúster>/latest.json` (gzip) en la cuenta
`K8S_SNAPSHOT_ACCOUNT`; el API la lee con su identidad administrada y calcula
aquí las incidencias y el score de salud. No toca el clúster ni la base.
"""

import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

STORAGE_SCOPE = "https://storage.azure.com/.default"
TIMEOUT = 20
# El agente sube cada 5 minutos: tres fotos perdidas ya es un agente caído.
VIEJA_SEGUNDOS = 15 * 60
# Un pod recién creado puede estar arrancando: no es incidencia todavía.
GRACIA_SEGUNDOS = 10 * 60
REINICIOS = 5

MOTIVOS_GRAVES = {"CrashLoopBackOff", "OOMKilled", "ImagePullBackOff", "ErrImagePull",
                  "CreateContainerConfigError", "CreateContainerError", "InvalidImageName"}
ORDEN = {"critica": 0, "alta": 1, "media": 2}


class FotoNoDisponible(RuntimeError):
    pass


def configurados() -> List[str]:
    return sorted({c.strip() for c in os.getenv("K8S_CLUSTERS", "").split(",") if c.strip()})


def leer(credenciales, nombre: str) -> Optional[Dict]:
    """La última foto del clúster, o None si su agente todavía no subió ninguna."""
    cuenta = os.getenv("K8S_SNAPSHOT_ACCOUNT", "")
    if not cuenta or credenciales is None:
        raise FotoNoDisponible("La lectura de clústeres no está configurada (K8S_SNAPSHOT_ACCOUNT).")
    token = credenciales.get_token(STORAGE_SCOPE).token
    try:
        r = requests.get(f"https://{cuenta}.blob.core.windows.net/k8s-{nombre}/latest.json",
                         headers={"Authorization": f"Bearer {token}", "x-ms-version": "2021-08-06"}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise FotoNoDisponible(f"El almacenamiento no respondió: {type(exc).__name__}") from None
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise FotoNoDisponible(f"El almacenamiento respondió {r.status_code} al leer {nombre}.")
    # requests descomprime solo: el blob se guarda con Content-Encoding: gzip.
    return r.json()


def _segundos(desde: Optional[str], ahora: datetime) -> Optional[float]:
    if not desde:
        return None
    return (ahora - datetime.fromisoformat(desde.replace("Z", "+00:00"))).total_seconds()


def _pod_con_problema(p: Dict, ahora: datetime) -> Optional[str]:
    """Severidad del problema del pod, o None si está sano."""
    if p["phase"] == "Succeeded":
        return None
    if p["reason"] == "Evicted":
        return "media"
    if p["reason"] in MOTIVOS_GRAVES:
        return "critica" if p["restarts"] > 10 else "alta"
    edad = _segundos(p.get("created"), ahora) or 0
    if p["phase"] in ("Pending", "Unknown", "Failed") and edad > GRACIA_SEGUNDOS:
        return "alta" if p["phase"] != "Failed" or p.get("owner_kind") != "Job" else "media"
    if p["restarts"] > REINICIOS:
        return "media"
    if p["phase"] == "Running" and p["ready"] < p["containers"] and edad > GRACIA_SEGUNDOS:
        return "media"
    return None


def incidencias(foto: Dict, ahora: datetime) -> List[Dict]:
    salida: List[Dict] = []

    def agregar(severidad, categoria, titulo, recurso, namespace, detalle, recomendacion):
        salida.append({"severity": severidad, "category": categoria, "title": titulo, "resource": recurso,
                       "namespace": namespace, "detail": detalle, "recommendation": recomendacion})

    for n in foto.get("nodes", []):
        if not n["ready"]:
            agregar("critica", "nodo", f"Nodo sin responder: {n['name']}", f"node/{n['name']}", None,
                    "El nodo no está Ready.", f"Revisa el kubelet del nodo (systemctl status kubelet) y kubectl describe node {n['name']}")
        for presion in n.get("pressure", []):
            agregar("alta", "nodo", f"{presion} en {n['name']}", f"node/{n['name']}", None,
                    f"El nodo reporta {presion}.", "Libera recursos o agrega capacidad; revisa los pods con más consumo del nodo")
    for p in foto.get("pods", []):
        severidad = _pod_con_problema(p, ahora)
        if severidad:
            motivo = p["reason"] or p["phase"]
            agregar(severidad, "pod", f"{motivo}: {p['name']}", f"pod/{p['name']}", p["namespace"],
                    f"Fase {p['phase']}, {p['ready']}/{p['containers']} listos, {p['restarts']} reinicios",
                    f"kubectl describe pod {p['name']} -n {p['namespace']} y kubectl logs {p['name']} -n {p['namespace']} --previous")
    for w in foto.get("workloads", []):
        if w["desired"] and w["ready"] < w["desired"]:
            agregar("alta" if w["ready"] == 0 else "media", "carga", f"{w['kind']} degradado: {w['name']}",
                    f"{w['kind'].lower()}/{w['name']}", w["namespace"], f"{w['ready']} de {w['desired']} réplicas listas",
                    f"kubectl rollout status {w['kind'].lower()}/{w['name']} -n {w['namespace']}")
    for s in foto.get("services", []):
        if s["selector"] and not s["headless"] and s["type"] != "ExternalName" and s["endpoints"] == 0:
            agregar("media", "red", f"Servicio sin endpoints: {s['name']}", f"svc/{s['name']}", s["namespace"],
                    "Ningún pod listo coincide con su selector.", "Compara el selector del servicio con las etiquetas de los pods")
    salida.sort(key=lambda i: ORDEN[i["severity"]])
    return salida


def salud(incid: List[Dict]) -> int:
    return max(0, 100 - sum({"critica": 25, "alta": 10, "media": 4}[i["severity"]] for i in incid))


def resumen(nombre: str, foto: Optional[Dict], ahora: datetime) -> Dict:
    if foto is None:
        return {"name": nombre, "reporting": False}
    incid = incidencias(foto, ahora)
    edad = _segundos(foto.get("collected_at"), ahora)
    pods = foto.get("pods", [])
    return {
        "name": nombre,
        "reporting": True,
        "distribution": foto.get("distribution"),
        "version": foto.get("kubernetes_version"),
        "agent_version": foto.get("agent_version"),
        "collected_at": foto.get("collected_at"),
        "age_seconds": int(edad) if edad is not None else None,
        "stale": edad is None or edad > VIEJA_SEGUNDOS,
        "nodes": len(foto.get("nodes", [])),
        "nodes_ready": sum(1 for n in foto.get("nodes", []) if n["ready"]),
        "pods": len(pods),
        "pods_running": sum(1 for p in pods if p["phase"] == "Running"),
        "namespaces": len(foto.get("namespaces", [])),
        "workloads": len(foto.get("workloads", [])),
        "health": salud(incid),
        "incidents": {s: sum(1 for i in incid if i["severity"] == s) for s in ORDEN},
    }


def detalle(nombre: str, foto: Dict, ahora: datetime) -> Dict:
    incid = incidencias(foto, ahora)
    problemas = {(i["namespace"], i["resource"]) for i in incid if i["category"] == "pod"}
    return {
        **resumen(nombre, foto, ahora),
        "incident_list": incid,
        "node_list": foto.get("nodes", []),
        "workload_list": sorted(foto.get("workloads", []), key=lambda w: (w["ready"] >= w["desired"], w["namespace"], w["name"])),
        "problem_pods": [p for p in foto.get("pods", []) if (p["namespace"], f"pod/{p['name']}") in problemas],
        "events": foto.get("events", [])[:50],
    }


def ahora() -> datetime:
    return datetime.now(timezone.utc)

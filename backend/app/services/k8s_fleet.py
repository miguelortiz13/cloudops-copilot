"""
Clústeres de Kubernetes desde las fotos que suben sus agentes (docs/plan/08-kubernetes.md).

Cada agente deja `k8s-<clúster>/latest.json` (gzip) en la cuenta
`K8S_SNAPSHOT_ACCOUNT`; el API la lee con su identidad administrada y calcula
aquí las incidencias y el score de salud. No toca el clúster ni la base.
"""

import os
import re
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests

STORAGE_SCOPE = "https://storage.azure.com/.default"
TIMEOUT = 20
# El agente sube cada 5 minutos: tres fotos perdidas ya es un agente caído.
VIEJA_SEGUNDOS = 15 * 60
# Un pod recién creado puede estar arrancando: no es incidencia todavía.
GRACIA_SEGUNDOS = 10 * 60
REINICIOS = 5
REINICIO_RECIENTE_SEGUNDOS = 3600

# "Error" es el mismo CrashLoop entre reinicios: sin él, la incidencia aparecería y desaparecería.
MOTIVOS_GRAVES = {"CrashLoopBackOff", "OOMKilled", "Error", "ImagePullBackOff", "ErrImagePull",
                  "CreateContainerConfigError", "CreateContainerError", "InvalidImageName"}
ORDEN = {"critica": 0, "alta": 1, "media": 2}


# Fin del soporte de cada versión menor de Kubernetes y su último parche, según el
# calendario oficial (https://endoflife.date/kubernetes, consultado el 24-oct-2026).
# AKS y EKS tienen calendarios propios, en general más largos; k3s y RKE2 siguen al
# upstream. Una versión que no está aquí se muestra "sin dato", nunca como vigente.
# shortcut: tabla fija; actualizarla al salir cada versión menor (~4 meses), o leerla de endoflife.date si pesa.
SOPORTE = {
    "1.37": ("2027-10-28", "1.37.1"), "1.36": ("2027-06-28", "1.36.5"), "1.35": ("2027-02-28", "1.35.9"),
    "1.34": ("2026-10-27", "1.34.12"), "1.33": ("2026-06-28", "1.33.13"), "1.32": ("2026-02-28", "1.32.13"),
    "1.31": ("2025-11-11", "1.31.14"), "1.30": ("2025-07-15", "1.30.14"), "1.29": ("2025-02-28", "1.29.15"),
    "1.28": ("2024-10-28", "1.28.15"), "1.27": ("2024-06-28", "1.27.16"), "1.26": ("2024-02-28", "1.26.15"),
}
POR_VENCER_DIAS = 90


class FotoNoDisponible(RuntimeError):
    pass


def soporte(version: Optional[str], ahora: datetime) -> Dict:
    """Fin de soporte de la versión: vigente, por_vencer (< 90 días), sin_soporte o sin_dato."""
    m = re.match(r"v?(\d+)\.(\d+)(?:\.(\d+))?", version or "")
    if not m:
        return {"status": "sin_dato", "minor": None, "eol": None, "latest_patch": None, "days_left": None}
    menor = f"{m.group(1)}.{m.group(2)}"
    if menor not in SOPORTE:
        return {"status": "sin_dato", "minor": menor, "eol": None, "latest_patch": None, "days_left": None}
    fin, parche = SOPORTE[menor]
    dias = (date.fromisoformat(fin) - ahora.date()).days
    estado = "sin_soporte" if dias < 0 else "por_vencer" if dias < POR_VENCER_DIAS else "vigente"
    actual = tuple(int(x) for x in m.groups(default="0"))
    return {"status": estado, "minor": menor, "eol": fin, "days_left": dias,
            "latest_patch": parche if tuple(int(x) for x in parche.split(".")) > actual else None}


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


def _reinicia_ahora(p: Dict, ahora: datetime) -> bool:
    """Más de 5 reinicios y el último hace menos de una hora (sin la hora, agente anterior a 1.2.1: basta el conteo)."""
    if p["restarts"] <= REINICIOS:
        return False
    if "last_restart" not in p:
        return True
    if p.get("last_restart_reason") == "Unknown":  # lo mató un reinicio del nodo (actualización, apagado), no la app
        return False
    edad = _segundos(p["last_restart"], ahora)
    return edad is not None and edad < REINICIO_RECIENTE_SEGUNDOS


def _pod_con_problema(p: Dict, ahora: datetime) -> Optional[Tuple[str, str]]:
    """(severidad, motivo) del problema del pod, o None si está sano."""
    if p["phase"] == "Succeeded":
        return None
    # Un Job fallido o un pod desalojado no son una carga caída.
    if p["reason"] == "Evicted" or (p["phase"] == "Failed" and p.get("owner_kind") == "Job"):
        return "media", p["reason"] or p["phase"]
    if p["reason"] in MOTIVOS_GRAVES:
        return ("critica" if p["restarts"] > 10 else "alta"), p["reason"]
    edad = _segundos(p.get("created"), ahora) or 0
    if p["phase"] in ("Pending", "Unknown", "Failed") and edad > GRACIA_SEGUNDOS:
        return "alta", p["reason"] or p["phase"]
    if _reinicia_ahora(p, ahora):
        return "media", "Reinicios frecuentes"
    if p["phase"] == "Running" and p["ready"] < p["containers"] and edad > GRACIA_SEGUNDOS:
        return "media", "Sin estar listo"
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
        problema = _pod_con_problema(p, ahora)
        if problema:
            severidad, motivo = problema
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
        "support": soporte(foto.get("kubernetes_version"), ahora),
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

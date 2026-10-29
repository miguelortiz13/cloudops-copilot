"""
Agente de CloudOps Copilot para Kubernetes (docs/plan/08-kubernetes.md).

Corre dentro del clúster con una ServiceAccount de solo lectura, arma una foto
resumida del estado (nodos, cargas, pods, servicios y eventos de advertencia) y
la sube comprimida a Azure Storage con una SAS que solo puede escribir en el
contenedor de este clúster. No abre puertos ni necesita que la plataforma
alcance el API server: sirve igual en AKS, EKS o un homelab.

Solo biblioteca estándar, para correr en la imagen oficial de Python sin
instalar nada:

    UPLOAD_URL=https://<cuenta>.blob.core.windows.net/k8s-<clúster>?<sas> python agent.py
    python agent.py --once      # una foto y termina
    python agent.py --print     # imprime la foto sin subirla

Nunca lee secrets ni configmaps, ni guarda variables de entorno o el spec
completo de los pods. De los pods con problemas incluye las últimas líneas de
log (con credenciales evidentes enmascaradas); INCLUDE_LOGS=false lo desactiva.
"""

import gzip
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Dict, Iterator, List, Optional

AGENT_VERSION = "1.2.1"
SCHEMA = 1
SA = "/var/run/secrets/kubernetes.io/serviceaccount"
MAX_EVENTS = 200
MAX_MESSAGE = 300
TIMEOUT = 30
MAX_LOGS = 10
LOG_LINES = 40
LOG_LINE_CHARS = 300
MOTIVOS_GRAVES = {"CrashLoopBackOff", "OOMKilled", "Error", "ImagePullBackOff", "ErrImagePull",
                  "CreateContainerConfigError", "CreateContainerError"}
# Lo que suele delatar una credencial en un log: el valor se reemplaza por ***.
_SECRETO = re.compile(r"(?i)((?:password|passwd|pwd|secret|token|api[_-]?key|authorization)[\"']?\s*[:=]\s*[\"']?)([^\s\"',;]+)")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[a-z0-9._~+/=-]{8,}")
_AWS_KEY = re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b")


class Kubernetes:
    """Cliente mínimo del API de Kubernetes con la ServiceAccount del pod."""

    def __init__(self):
        host = os.environ["KUBERNETES_SERVICE_HOST"]
        port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
        self.base = f"https://{host}:{port}"
        contexto = ssl.create_default_context(cafile=f"{SA}/ca.crt")
        # El API del clúster nunca pasa por el proxy de salida (HTTPS_PROXY) que
        # sí puede necesitar la subida a Azure.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                  urllib.request.HTTPSHandler(context=contexto))

    def _abrir(self, ruta: str):
        # El token proyectado rota: se lee en cada llamada.
        with open(f"{SA}/token") as f:
            token = f.read().strip()
        peticion = urllib.request.Request(self.base + ruta, headers={"Authorization": f"Bearer {token}"})
        return self.opener.open(peticion, timeout=TIMEOUT)

    def get(self, ruta: str) -> Dict:
        with self._abrir(ruta) as r:
            return json.load(r)

    def texto(self, ruta: str) -> str:
        with self._abrir(ruta) as r:
            return r.read().decode("utf-8", errors="replace")

    def listar(self, ruta: str, **params) -> Iterator[Dict]:
        """Todos los elementos de una lista, de 500 en 500."""
        continuar = ""
        while True:
            consulta = {"limit": 500, **params, **({"continue": continuar} if continuar else {})}
            datos = self.get(f"{ruta}?{urllib.parse.urlencode(consulta)}")
            yield from datos.get("items", [])
            continuar = datos.get("metadata", {}).get("continue")
            if not continuar:
                return


def milicores(valor: Optional[str]) -> Optional[int]:
    if not valor:
        return None
    return int(valor[:-1]) if valor.endswith("m") else int(float(valor) * 1000)


def mebibytes(valor: Optional[str]) -> Optional[int]:
    if not valor:
        return None
    unidades = {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "Ti": 1024 ** 2, "K": 1e3 / 2 ** 20, "M": 1e6 / 2 ** 20, "G": 1e9 / 2 ** 20}
    for sufijo, factor in unidades.items():
        if valor.endswith(sufijo):
            return int(float(valor[: -len(sufijo)]) * factor)
    return int(int(valor) / 2 ** 20)


def nodo(n: Dict) -> Dict:
    meta, estado = n["metadata"], n.get("status", {})
    condiciones = {c["type"]: c.get("status") for c in estado.get("conditions", [])}
    info = estado.get("nodeInfo", {})
    capacidad = estado.get("capacity", {})
    return {
        "name": meta["name"],
        "ready": condiciones.get("Ready") == "True",
        "pressure": sorted(t for t in ("MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable")
                           if condiciones.get(t) == "True"),
        "unschedulable": bool(n.get("spec", {}).get("unschedulable")),
        "roles": sorted(k.split("/", 1)[1] for k in meta.get("labels", {}) if k.startswith("node-role.kubernetes.io/")) or ["worker"],
        "kubelet": info.get("kubeletVersion"),
        "os": info.get("osImage"),
        "runtime": info.get("containerRuntimeVersion"),
        "arch": info.get("architecture"),
        "cpu_m": milicores(capacidad.get("cpu")),
        "memory_mib": mebibytes(capacidad.get("memory")),
        "created": meta.get("creationTimestamp"),
    }


def _motivo(estado: Dict) -> Optional[str]:
    """Por qué un pod no está sano: el contenedor que espera o terminó mal, o el motivo del pod."""
    for c in estado.get("containerStatuses", []) + estado.get("initContainerStatuses", []):
        espera = c.get("state", {}).get("waiting", {}).get("reason")
        if espera and espera not in ("ContainerCreating", "PodInitializing"):
            return espera
        fin = c.get("state", {}).get("terminated", {}).get("reason")
        if fin and fin != "Completed":
            return fin
    for c in estado.get("containerStatuses", []):
        if c.get("lastState", {}).get("terminated", {}).get("reason") == "OOMKilled":
            return "OOMKilled"
    return estado.get("reason")


def pod(p: Dict) -> Dict:
    meta, spec, estado = p["metadata"], p.get("spec", {}), p.get("status", {})
    contenedores = estado.get("containerStatuses", [])
    duenos = meta.get("ownerReferences") or [{}]
    return {
        "namespace": meta["namespace"],
        "name": meta["name"],
        "phase": estado.get("phase", "Unknown"),
        "reason": _motivo(estado),
        "ready": sum(1 for c in contenedores if c.get("ready")),
        "containers": len(spec.get("containers", [])),
        "restarts": sum(c.get("restartCount", 0) for c in contenedores),
        # El contador de reinicios es acumulado: sin la hora del último, un clúster
        # que se apagó y volvió a encender parece tener todos sus pods fallando.
        "last_restart": max((c.get("lastState", {}).get("terminated", {}).get("finishedAt") or ""
                             for c in contenedores), default="") or None,
        "node": spec.get("nodeName"),
        "owner_kind": duenos[0].get("kind"),
        "owner": duenos[0].get("name"),
        "created": meta.get("creationTimestamp"),
    }


def seguridad(plantilla: Dict) -> Dict:
    """
    Banderas de seguridad de la plantilla de pods de una carga, para las reglas
    del catálogo (docs/plan/08-kubernetes.md, parte 3). Solo banderas: ni
    comandos, ni variables de entorno, ni rutas montadas.
    """
    spec = plantilla.get("spec", {})
    pod_sc = spec.get("securityContext") or {}
    contenedores = []
    for c in spec.get("containers", []) + spec.get("initContainers", []):
        sc = c.get("securityContext") or {}
        usuario = sc.get("runAsUser", pod_sc.get("runAsUser"))
        contenedores.append({
            "name": c["name"],
            "image": c.get("image"),
            "limits": bool((c.get("resources") or {}).get("limits")),
            "privileged": bool(sc.get("privileged")),
            # Solo un false explícito impide escalar privilegios.
            "no_escalation": sc.get("allowPrivilegeEscalation") is False and not sc.get("privileged"),
            "non_root": sc.get("runAsNonRoot", pod_sc.get("runAsNonRoot")) is True or (usuario is not None and usuario != 0),
        })
    return {"host_network": bool(spec.get("hostNetwork")), "host_pid": bool(spec.get("hostPID")),
            "host_ipc": bool(spec.get("hostIPC")),
            "host_path": any("hostPath" in v for v in spec.get("volumes") or []),
            "containers": contenedores}


def carga(tipo: str, w: Dict) -> Dict:
    spec, estado = w.get("spec", {}), w.get("status", {})
    if tipo == "DaemonSet":
        deseadas, listas = estado.get("desiredNumberScheduled", 0), estado.get("numberReady", 0)
    else:
        deseadas, listas = spec.get("replicas", 1), estado.get("readyReplicas", 0)
    return {"kind": tipo, "namespace": w["metadata"]["namespace"], "name": w["metadata"]["name"],
            "desired": deseadas, "ready": listas, "created": w["metadata"].get("creationTimestamp"),
            "security": seguridad(spec.get("template", {}))}


def servicio(s: Dict, listos: Dict[str, int]) -> Dict:
    meta, spec = s["metadata"], s.get("spec", {})
    return {"namespace": meta["namespace"], "name": meta["name"], "type": spec.get("type"),
            "selector": bool(spec.get("selector")), "headless": spec.get("clusterIP") == "None",
            "endpoints": listos.get(f"{meta['namespace']}/{meta['name']}", 0)}


def evento(e: Dict) -> Dict:
    objeto = e.get("involvedObject", {})
    return {"namespace": e["metadata"].get("namespace"), "kind": objeto.get("kind"), "name": objeto.get("name"),
            "reason": e.get("reason"), "message": (e.get("message") or "")[:MAX_MESSAGE],
            "count": e.get("count") or 1,
            "last": e.get("lastTimestamp") or e.get("eventTime") or e["metadata"].get("creationTimestamp")}


def distribucion(version: str, nodos: List[Dict]) -> str:
    etiquetas = {k: v for n in nodos for k, v in n.get("metadata", {}).get("labels", {}).items()}
    if "kubernetes.azure.com/cluster" in etiquetas:
        return "aks"
    if "-eks-" in version or any(k.startswith("eks.amazonaws.com/") for k in etiquetas):
        return "eks"
    if "-gke." in version:
        return "gke"
    for marca in ("k3s", "rke2", "k0s"):
        if f"+{marca}" in version:
            return marca
    if etiquetas.get("node.kubernetes.io/instance-type") == "k3s":
        return "k3s"
    return "kubernetes"


def enmascarar(linea: str) -> str:
    linea = _BEARER.sub(lambda m: m.group(1) + " ***", linea)
    linea = _SECRETO.sub(lambda m: m.group(1) + "***", linea)
    return _AWS_KEY.sub("***", linea)[:LOG_LINE_CHARS]


def con_problema(p: Dict) -> Optional[str]:
    """Contenedor del pod cuyo log explica el problema, o None si el pod está sano."""
    estado = p.get("status", {})
    for c in estado.get("containerStatuses", []):
        espera = c.get("state", {}).get("waiting", {}).get("reason")
        fin = c.get("lastState", {}).get("terminated", {}).get("reason")
        if espera in MOTIVOS_GRAVES or (c.get("restartCount", 0) and not c.get("ready")) or fin == "OOMKilled":
            return c["name"]
    if estado.get("phase") == "Failed" and p.get("spec", {}).get("containers"):
        return p["spec"]["containers"][0]["name"]
    return None


def log(k: Kubernetes, p: Dict, contenedor: str) -> Optional[Dict]:
    """Últimas líneas del contenedor: las de la ejecución anterior si se reinició (ahí está el error)."""
    meta = p["metadata"]
    reinicios = next((c.get("restartCount", 0) for c in p.get("status", {}).get("containerStatuses", [])
                      if c["name"] == contenedor), 0)
    base = f"/api/v1/namespaces/{meta['namespace']}/pods/{meta['name']}/log"
    for anterior in ([True, False] if reinicios else [False]):
        consulta = urllib.parse.urlencode({"container": contenedor, "tailLines": LOG_LINES, "limitBytes": 16384,
                                           **({"previous": "true"} if anterior else {})})
        try:
            lineas = k.texto(f"{base}?{consulta}").splitlines()[-LOG_LINES:]
        except (urllib.error.URLError, OSError):
            continue
        # El kubelet responde 200 con este texto si el contenedor anterior ya no existe.
        if not lineas or lineas[0].startswith("unable to retrieve container logs"):
            continue
        return {"container": contenedor, "previous": anterior, "lines": [enmascarar(x) for x in lineas]}
    return None


def foto(k: Kubernetes, cluster: str, con_logs: bool = True) -> Dict:
    version = k.get("/version").get("gitVersion", "")
    nodos = list(k.listar("/api/v1/nodes"))
    listos: Dict[str, int] = {}
    for s in k.listar("/apis/discovery.k8s.io/v1/endpointslices"):
        dueno = s["metadata"].get("labels", {}).get("kubernetes.io/service-name")
        if dueno:
            clave = f"{s['metadata']['namespace']}/{dueno}"
            listos[clave] = listos.get(clave, 0) + sum(
                1 for e in s.get("endpoints") or [] if (e.get("conditions") or {}).get("ready", True))
    pods_crudos = list(k.listar("/api/v1/pods"))
    pods = [pod(p) for p in pods_crudos]
    if con_logs:
        problemas = [(i, c) for i, p in enumerate(pods_crudos) if (c := con_problema(p))][:MAX_LOGS]
        for i, contenedor in problemas:
            registro = log(k, pods_crudos[i], contenedor)
            if registro:
                pods[i]["log"] = registro
    eventos = sorted((evento(e) for e in k.listar("/api/v1/events", fieldSelector="type=Warning")),
                     key=lambda e: e["last"] or "", reverse=True)[:MAX_EVENTS]
    return {
        "schema": SCHEMA,
        "agent_version": AGENT_VERSION,
        "cluster": cluster,
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kubernetes_version": version,
        "distribution": distribucion(version, nodos),
        "namespaces": sorted(n["metadata"]["name"] for n in k.listar("/api/v1/namespaces")),
        "nodes": [nodo(n) for n in nodos],
        "workloads": [carga(tipo, w) for tipo, ruta in (("Deployment", "deployments"), ("StatefulSet", "statefulsets"),
                                                         ("DaemonSet", "daemonsets"))
                      for w in k.listar(f"/apis/apps/v1/{ruta}")],
        "pods": pods,
        "services": [servicio(s, listos) for s in k.listar("/api/v1/services")],
        "events": eventos,
    }


def subir(url_contenedor: str, datos: Dict) -> None:
    """PUT de latest.json en el contenedor del clúster (la SAS solo permite crear y escribir)."""
    base, _, sas = url_contenedor.partition("?")
    cuerpo = gzip.compress(json.dumps(datos, separators=(",", ":")).encode())
    peticion = urllib.request.Request(
        f"{base.rstrip('/')}/latest.json?{sas}", data=cuerpo, method="PUT",
        headers={"x-ms-blob-type": "BlockBlob", "x-ms-version": "2021-08-06",
                 "Content-Type": "application/json", "Content-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT):
            pass
    except urllib.error.HTTPError as exc:
        # La URL lleva la SAS: el error solo muestra el host.
        raise RuntimeError(f"{urllib.parse.urlparse(base).hostname} respondió {exc.code}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{urllib.parse.urlparse(base).hostname} no respondió: {exc.reason}") from None


def main(argv: List[str]) -> int:
    cluster = os.environ.get("CLUSTER_NAME", "cluster")
    intervalo = int(os.environ.get("INTERVAL_SECONDS", "300"))
    url = os.environ.get("UPLOAD_URL", "")
    if "--print" not in argv and not url:
        print("Falta UPLOAD_URL (la URL del contenedor con su SAS).", file=sys.stderr)
        return 2
    k = Kubernetes()
    while True:
        inicio = time.monotonic()
        try:
            datos = foto(k, cluster, con_logs=os.environ.get("INCLUDE_LOGS", "true").lower() != "false")
            if "--print" in argv:
                print(json.dumps(datos, indent=2))
            else:
                subir(url, datos)
                print(f"[agente] {datos['collected_at']} foto subida: {len(datos['nodes'])} nodos, "
                      f"{len(datos['pods'])} pods, {len(datos['events'])} eventos", flush=True)
        except Exception as exc:  # una foto fallida no detiene al agente
            print(f"[agente] error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            if "--once" in argv or "--print" in argv:
                return 1
        if "--once" in argv or "--print" in argv:
            return 0
        time.sleep(max(10, intervalo - (time.monotonic() - inicio)))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""
k8s_service.py — Motor del Agente Kubernetes SRE.
Adaptado para usar AKS Run Command (cero impacto, salta restricciones de red/Private Clusters).
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app import llm
from app.core import config

logger = logging.getLogger(__name__)


class K8sInputError(ValueError):
    """Un identificador de Kubernetes recibido del cliente no es valido."""


# Nombres validos segun RFC 1123, que es lo que acepta Kubernetes: minusculas,
# digitos, guiones y puntos, empezando y terminando en alfanumerico.
_NOMBRE_K8S = re.compile(r"^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$")

# Caracteres con significado para el shell. El comando viaja a AKS Run Command,
# que lo ejecuta en un pod del clúster con permisos de administrador: cualquiera
# de estos convierte una consulta de diagnostico en escritura sobre el clúster.
_METACARACTERES = set(";|&$`\n\r<>(){}[]!*?\\\"'")


def _validar_nombre(valor: Optional[str], campo: str) -> Optional[str]:
    """
    Comprueba que un identificador que llega del cliente puede incrustarse en un
    comando kubectl.

    La plataforma es de solo lectura por diseño y este es el unico camino que
    ejecuta algo dentro de la infraestructura. Sin esta validacion, un
    `?pod=x;kubectl delete ns prod` en la URL se ejecuta tal cual.
    """
    if valor is None:
        return None
    valor = valor.strip()
    if not valor:
        return None
    if not _NOMBRE_K8S.match(valor):
        raise K8sInputError(
            f"El valor de '{campo}' no es un identificador valido de Kubernetes: {valor!r}"
        )
    return valor

try:
    from azure.mgmt.containerservice import ContainerServiceClient
    from azure.mgmt.containerservice.models import RunCommandRequest
    HAS_AKS_SDK = True
except ImportError:
    HAS_AKS_SDK = False

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _age_str(creation_timestamp) -> str:
    try:
        if not creation_timestamp: return "unknown"
        # Parse ISO8601 from kubectl output
        if isinstance(creation_timestamp, str):
            creation_timestamp = datetime.fromisoformat(creation_timestamp.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        delta = now - creation_timestamp
        total_seconds = int(delta.total_seconds())
        if total_seconds < 3600: return f"{total_seconds // 60}m"
        elif total_seconds < 86400: return f"{total_seconds // 3600}h"
        else: return f"{total_seconds // 86400}d"
    except:
        return "unknown"

def _health_score(incidents: List[Dict]) -> int:
    penalty = sum({"CRITICAL": 25, "HIGH": 10, "MEDIUM": 4, "LOW": 1}.get(i.get("severity"), 0) for i in incidents)
    return max(0, 100 - penalty)


class K8sService:
    def __init__(self, azure=None):
        self.azure = azure
        self._init_client()

    def _init_client(self) -> None:
        """
        Lee la configuracion del clúster y abre el cliente de AKS.

        Vive aparte del constructor para que `/api/k8s/reinit` pueda rehacer la
        conexion cuando cambian las variables K8S_* sin reiniciar el servicio,
        que es justo lo que ese endpoint promete.
        """
        self.cluster_name = os.getenv("K8S_CLUSTER_NAME")
        self.resource_group = os.getenv("K8S_RESOURCE_GROUP")
        self.subscription_id = os.getenv("K8S_SUBSCRIPTION_ID")
        self.connection_mode = "aks_run_command" if all([self.cluster_name, self.resource_group, self.subscription_id]) else "offline"
        self._server_version = "unknown"

        if self.connection_mode != "offline" and HAS_AKS_SDK and self.azure:
            self.aks_client = ContainerServiceClient(self.azure.azure_credentials, self.subscription_id)
        else:
            self.aks_client = None

    @staticmethod
    def _assert_sin_metacaracteres(command: str) -> None:
        """
        Ultima barrera antes de ejecutar: ningun comando armado por la
        plataforma necesita metacaracteres de shell, asi que su presencia
        significa que un valor externo se colo sin validar.
        """
        sospechosos = _METACARACTERES.intersection(command)
        if sospechosos:
            raise K8sInputError(
                "Comando kubectl rechazado por contener caracteres de shell: "
                + " ".join(sorted(sospechosos))
            )

    def _run_kubectl(self, command: str) -> Optional[Dict]:
        """Ejecuta un comando en el clúster usando AKS Run Command."""
        if not self.aks_client:
            return None
        self._assert_sin_metacaracteres(command)
        try:
            req = RunCommandRequest(command=f"kubectl {command}", context="")
            poller = self.aks_client.managed_clusters.begin_run_command(self.resource_group, self.cluster_name, req)
            result = poller.result()
            if result.logs:
                return json.loads(result.logs)
            return None
        except Exception as e:
            logger.error(f"Error run_command '{command}': {e}")
            return None
            
    def _run_kubectl_text(self, command: str) -> str:
        if not self.aks_client:
            return ""
        self._assert_sin_metacaracteres(command)
        try:
            req = RunCommandRequest(command=f"kubectl {command}", context="")
            poller = self.aks_client.managed_clusters.begin_run_command(self.resource_group, self.cluster_name, req)
            result = poller.result()
            return result.logs or ""
        except Exception as e:
            return f"Error: {e}"

    def health(self) -> Dict:
        return {
            "status": "ok" if self.aks_client else "offline",
            "connectionMode": self.connection_mode,
            "clusterConfigured": self.aks_client is not None,
            "serverVersion": "Managed by AKS",
            "message": "Conectado vía AKS Run Command (API de Azure ARM)." if self.aks_client else "Faltan credenciales K8S_*",
            "timestamp": _now_iso(),
        }

    def list_aks_clusters(self, subscription_ids: Optional[List[str]] = None) -> Dict:
        clusters = []
        if self.azure and hasattr(self.azure, "query_azure_resource_graph"):
            kql = (
                "resources "
                "| where type =~ 'microsoft.containerservice/managedclusters' "
                "| project name, resourceGroup, subscriptionId, location, "
                "  k8sVersion = tostring(properties.kubernetesVersion), "
                "  provisioningState = tostring(properties.provisioningState), "
                "  powerState = tostring(properties.powerState.code), "
                "  fqdn = tostring(properties.fqdn), "
                "  nodeCount = toint(properties.agentPoolProfiles[0].count)"
            )
            try:
                raw = self.azure.query_azure_resource_graph(kql, subscriptions=subscription_ids or [])
                for r in raw:
                    clusters.append(r)
            except Exception as e:
                logger.error(f"Error listing clusters: {e}")
        return {"clusters": clusters, "total": len(clusters), "scannedAt": _now_iso()}

    # --- Herramientas reescritas para usar `get <resource> -o json` ---

    def _get_problem_pods(self, namespace: Optional[str] = None) -> List[Dict]:
        namespace = _validar_nombre(namespace, "namespace")
        ns_flag = f"-n {namespace}" if namespace else "-A"
        data = self._run_kubectl(f"get pods {ns_flag} -o json")
        if not data: return []
        
        problems = []
        for pod in data.get("items", []):
            meta = pod.get("metadata", {})
            status = pod.get("status", {})
            phase = status.get("phase", "Unknown")
            
            c_statuses = status.get("containerStatuses", [])
            
            restarts = sum(cs.get("restartCount", 0) for cs in c_statuses)
            ready = sum(1 for cs in c_statuses if cs.get("ready"))
            total = len(c_statuses)
            
            # Detect issues
            crash_loop = any(cs.get("state", {}).get("waiting", {}).get("reason") in ("CrashLoopBackOff", "Error", "OOMKilled") for cs in c_statuses)
            oom = any(cs.get("state", {}).get("terminated", {}).get("reason") == "OOMKilled" for cs in c_statuses)
            
            pod_reason = phase
            if crash_loop: pod_reason = "CrashLoopBackOff"
            elif oom: pod_reason = "OOMKilled"
            
            if phase not in ("Running", "Succeeded") or crash_loop or oom or restarts > 5:
                problems.append({
                    "name": meta.get("name"),
                    "namespace": meta.get("namespace"),
                    "status": pod_reason,
                    "restarts": restarts,
                    "ready": f"{ready}/{total}",
                    "age": _age_str(meta.get("creationTimestamp")),
                    "node": pod.get("spec", {}).get("nodeName"),
                    "reason": pod_reason
                })
        return problems

    def _get_nodes_status(self) -> Tuple[List[Dict], int, int]:
        data = self._run_kubectl("get nodes -o json")
        if not data: return [], 0, 0
        
        nodes = []
        total = ready_count = 0
        for node in data.get("items", []):
            total += 1
            meta = node.get("metadata", {})
            status = node.get("status", {})
            conds = status.get("conditions", [])
            
            state = "Unknown"
            prob_conds = []
            for c in conds:
                if c.get("type") == "Ready": state = "Ready" if c.get("status") == "True" else "NotReady"
                elif c.get("type") in ("MemoryPressure", "DiskPressure", "NetworkUnavailable") and c.get("status") == "True":
                    prob_conds.append(c.get("type"))
            
            if state == "Ready": ready_count += 1
            
            roles = [k.split("/")[-1] for k in meta.get("labels", {}).keys() if k.startswith("node-role.kubernetes.io/")] or ["worker"]
            nodes.append({
                "name": meta.get("name"),
                "status": state,
                "roles": roles,
                "conditions": prob_conds,
                "cpuCapacity": status.get("capacity", {}).get("cpu"),
                "memCapacity": status.get("capacity", {}).get("memory"),
                "k8sVersion": status.get("nodeInfo", {}).get("kubeletVersion"),
                "age": _age_str(meta.get("creationTimestamp"))
            })
        return nodes, total, ready_count

    def _get_services_without_endpoints(self, namespace: Optional[str] = None) -> List[Dict]:
        namespace = _validar_nombre(namespace, "namespace")
        ns_flag = f"-n {namespace}" if namespace else "-A"
        svcs = self._run_kubectl(f"get svc {ns_flag} -o json")
        eps = self._run_kubectl(f"get endpoints {ns_flag} -o json")
        if not svcs or not eps: return []
        
        ep_map = {f"{e['metadata']['namespace']}/{e['metadata']['name']}": e for e in eps.get("items", [])}
        probs = []
        
        for svc in svcs.get("items", []):
            spec = svc.get("spec", {})
            meta = svc.get("metadata", {})
            if spec.get("type") == "ExternalName" or spec.get("clusterIP") in ("None", ""): continue
            
            ep = ep_map.get(f"{meta['namespace']}/{meta['name']}", {})
            has_endpoints = any(s.get("addresses") for s in ep.get("subsets", []))
            
            if not has_endpoints:
                probs.append({
                    "name": meta.get("name"),
                    "namespace": meta.get("namespace"),
                    "type": spec.get("type"),
                    "clusterIP": spec.get("clusterIP"),
                    "ports": [f"{p.get('port')}/{p.get('protocol')}" for p in spec.get("ports", [])],
                    "hasEndpoints": False
                })
        return probs

    def get_pod_logs(self, pod_name: str, namespace: str, container: Optional[str] = None, tail_lines: int = 100) -> Dict:
        pod_name = _validar_nombre(pod_name, "pod")
        namespace = _validar_nombre(namespace, "namespace")
        container = _validar_nombre(container, "container")
        if not pod_name or not namespace:
            raise K8sInputError("Se requieren 'pod' y 'namespace' para leer logs.")
        try:
            tail_lines = max(1, min(int(tail_lines), 500))
        except (TypeError, ValueError):
            tail_lines = 100
        c_flag = f"-c {container}" if container else ""
        logs = self._run_kubectl_text(f"logs {pod_name} -n {namespace} {c_flag} --tail={tail_lines} --timestamps=true")
        return {
            "pod": pod_name,
            "namespace": namespace,
            "container": container,
            "lines": len(logs.splitlines()),
            "logs": logs or "(sin logs)",
            "retrievedAt": _now_iso(),
        }

    # (Métodos auxiliares resumidos por longitud. La lógica de evaluación usa las salidas JSON.)
    def _build_incidents(self, problem_pods, nodes, services_no_ep) -> List[Dict]:
        incidents = []
        for pod in problem_pods:
            r = pod.get("restarts", 0)
            sev = "CRITICAL" if pod["reason"] in ("OOMKilled", "CrashLoopBackOff") and r > 10 else "HIGH" if pod["reason"] in ("Pending", "CrashLoopBackOff") else "MEDIUM"
            incidents.append({
                "severity": sev,
                "category": "WORKLOAD",
                "title": f"Pod {pod['reason']}: {pod['name']}",
                "resource": f"pod/{pod['name']}",
                "namespace": pod["namespace"],
                "detail": f"Status: {pod['status']} | Restarts: {r}",
                "recommendation": f"Revisa logs: kubectl logs {pod['name']} -n {pod['namespace']}"
            })
        
        for node in nodes:
            if node["status"] == "NotReady":
                incidents.append({"severity":"CRITICAL", "category":"NODE", "title":f"Nodo NotReady: {node['name']}", "detail":"Not Ready", "recommendation":"systemctl status kubelet", "namespace":None, "resource":f"node/{node['name']}"})
        
        for svc in services_no_ep:
            incidents.append({"severity":"MEDIUM", "category":"NETWORK", "title":f"Service sin endpoints: {svc['name']}", "detail":f"Tipo: {svc['type']}", "recommendation":f"Verifica labels del deployment detrás del service", "namespace":svc['namespace'], "resource":f"svc/{svc['name']}"})
            
        incidents.sort(key=lambda i: SEVERITY_ORDER.get(i["severity"], 99))
        return incidents

    def get_incidents(self, cluster_request: Dict) -> Dict:
        ns = cluster_request.get("namespace")
        incidents = self._build_incidents(self._get_problem_pods(ns), self._get_nodes_status()[0], self._get_services_without_endpoints(ns))
        
        summary = {s: sum(1 for i in incidents if i["severity"] == s.upper()) for s in ["critical", "high", "medium", "low", "info"]}
        summary["total"] = len(incidents)
        
        return {
            "clusterName": self.cluster_name,
            "clusterHealthScore": _health_score(incidents),
            "incidents": incidents,
            "summary": summary,
            "scannedAt": _now_iso(),
            "connectionMode": self.connection_mode,
        }

    def get_overview(self, cluster_request: Dict) -> Dict:
        nodes, nt, nr = self._get_nodes_status()
        return {
            "clusterName": self.cluster_name,
            "nodeCount": nt,
            "nodesReady": nr,
            "problemPodsList": self._get_problem_pods(cluster_request.get("namespace")),
            "scannedAt": _now_iso(),
            "connectionMode": self.connection_mode,
            "degradedWorkloads": [], "recentWarningEvents": [], "pendingPVCs": [], "servicesWithoutEndpoints": [], "podCount":0, "podsRunning":0, "problemPods":0, "namespaceCount":0, "nodes": nodes
        }

    def chat(self, question: str, cluster_request: Dict, usuario: Optional[str] = None) -> Dict:
        incidents = self.get_incidents(cluster_request)
        nodes, nt, nr = self._get_nodes_status()
        
        context = {
            "cluster_name": self.cluster_name,
            "nodes_total": nt, "nodes_ready": nr,
            "problem_pods": self._get_problem_pods(cluster_request.get("namespace"))[:5],
            "incidents_summary": incidents["summary"]
        }

        resumen = (f"## Clúster: {self.cluster_name}\n**Salud:** {incidents['clusterHealthScore']}/100 · "
                   f"nodos listos {nr}/{nt}\n\n" + "\n".join(
                       f"- {sev}: {n}" for sev, n in (incidents.get("summary") or {}).items() if n))
        if not llm.disponible():
            answer, mode = resumen + "\n\n*Sin modelo de lenguaje configurado: se muestra el estado del clúster.*", "rules"
        else:
            sistema = (f"Eres el Agente SRE Kubernetes de {config.ORG_NAME}. Tienes acceso al clúster vía Run Command. "
                       "Usa el contexto JSON para responder con Markdown y sugerir comandos kubectl.")
            try:
                r = llm.generar("k8s.chat", sistema, f"Contexto:\n{json.dumps(context)}\n\nPregunta: {question}",
                                usuario=usuario)
                answer, mode = r.texto, f"llm_{llm.proveedor().nombre}"
            except llm.LLMError as e:
                logger.error(f"Modelo no disponible: {e}")
                answer, mode = resumen + "\n\n*El modelo de lenguaje no respondió; se muestra el estado del clúster.*", "fallback"

        return {"answer": answer, "mode": mode, "context_summary": {"healthScore": incidents["clusterHealthScore"], "incidentsSummary": incidents["summary"], "nodesReady": f"{nr}/{nt}"}}

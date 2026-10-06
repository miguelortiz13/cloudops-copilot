"""
k8s.py — Schemas Pydantic para el módulo de Kubernetes SRE.
"""

from typing import List, Optional
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class K8sClusterRequest(BaseModel):
    clusterName: Optional[str] = None          # Nombre del clúster AKS
    resourceGroup: Optional[str] = None        # RG del clúster en Azure
    subscriptionId: Optional[str] = None       # Suscripción del clúster
    namespace: Optional[str] = None            # Filtrar por namespace (opcional)
    kubeconfig: Optional[str] = None           # Kubeconfig en base64 (opcional)


class K8sChatRequest(BaseModel):
    message: str
    clusterName: Optional[str] = None
    resourceGroup: Optional[str] = None
    subscriptionId: Optional[str] = None
    namespace: Optional[str] = None


# ---------------------------------------------------------------------------
# Response models — Incidencias
# ---------------------------------------------------------------------------

class K8sIncident(BaseModel):
    severity: str                              # CRITICAL | HIGH | MEDIUM | LOW | INFO
    category: str                              # WORKLOAD | NODE | NETWORK | STORAGE | CONFIG
    title: str
    resource: Optional[str] = None
    namespace: Optional[str] = None
    detail: str
    recommendation: str
    since: Optional[str] = None
    count: Optional[int] = None                # Número de ocurrencias


class K8sIncidentSummary(BaseModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0
    total: int = 0


class K8sIncidentsResponse(BaseModel):
    clusterName: Optional[str] = None
    clusterHealthScore: int                    # 0-100
    incidents: List[K8sIncident]
    summary: K8sIncidentSummary
    scannedAt: str
    connectionMode: str                        # aks_api | kubeconfig | offline


# ---------------------------------------------------------------------------
# Response models — Overview
# ---------------------------------------------------------------------------

class K8sNodeInfo(BaseModel):
    name: str
    status: str                                # Ready | NotReady | Unknown
    roles: List[str]
    conditions: List[str]                      # Condiciones activas problemáticas
    cpuCapacity: Optional[str] = None
    memCapacity: Optional[str] = None
    k8sVersion: Optional[str] = None
    age: Optional[str] = None


class K8sPodInfo(BaseModel):
    name: str
    namespace: str
    status: str                                # Running | CrashLoopBackOff | Pending | Error
    restarts: int = 0
    ready: str                                 # "1/1", "0/1"
    age: Optional[str] = None
    node: Optional[str] = None
    reason: Optional[str] = None              # OOMKilled, Error, etc.


class K8sWorkloadInfo(BaseModel):
    name: str
    namespace: str
    kind: str                                  # Deployment | StatefulSet | DaemonSet
    desiredReplicas: int
    readyReplicas: int
    availableReplicas: int
    isDegraded: bool
    age: Optional[str] = None


class K8sEventInfo(BaseModel):
    namespace: str
    kind: str                                  # Pod | Node | Deployment...
    name: str
    reason: str                                # OOMKilling | BackOff | FailedMount...
    message: str
    count: int
    lastSeen: Optional[str] = None
    type: str                                  # Warning | Normal


class K8sPVCInfo(BaseModel):
    name: str
    namespace: str
    status: str                                # Bound | Pending | Lost
    storageClass: Optional[str] = None
    capacity: Optional[str] = None
    volumeName: Optional[str] = None


class K8sServiceInfo(BaseModel):
    name: str
    namespace: str
    type: str                                  # ClusterIP | LoadBalancer | NodePort
    clusterIP: Optional[str] = None
    externalIP: Optional[str] = None
    ports: List[str]
    hasEndpoints: bool


class K8sOverviewResponse(BaseModel):
    clusterName: Optional[str] = None
    k8sVersion: Optional[str] = None
    nodeCount: int
    nodesReady: int
    podCount: int
    podsRunning: int
    problemPods: int
    namespaceCount: int
    nodes: List[K8sNodeInfo]
    problemPodsList: List[K8sPodInfo]
    degradedWorkloads: List[K8sWorkloadInfo]
    recentWarningEvents: List[K8sEventInfo]
    pendingPVCs: List[K8sPVCInfo]
    servicesWithoutEndpoints: List[K8sServiceInfo]
    scannedAt: str
    connectionMode: str


# ---------------------------------------------------------------------------
# Response models — Health endpoint
# ---------------------------------------------------------------------------

class K8sHealthResponse(BaseModel):
    status: str                                # ok | offline | error
    connectionMode: str                        # aks_api | kubeconfig | offline
    clusterConfigured: bool
    serverVersion: Optional[str] = None
    message: Optional[str] = None
    timestamp: str


# ---------------------------------------------------------------------------
# Response models — Clusters list
# ---------------------------------------------------------------------------

class K8sClusterListItem(BaseModel):
    name: str
    resourceGroup: str
    subscriptionId: str
    subscriptionName: Optional[str] = None
    location: str
    k8sVersion: Optional[str] = None
    provisioningState: Optional[str] = None
    powerState: Optional[str] = None
    nodeCount: Optional[int] = None
    fqdn: Optional[str] = None


class K8sClusterListResponse(BaseModel):
    clusters: List[K8sClusterListItem]
    total: int
    scannedAt: str


# ---------------------------------------------------------------------------
# Response models — Logs
# ---------------------------------------------------------------------------

class K8sPodLogsResponse(BaseModel):
    pod: str
    namespace: str
    container: Optional[str] = None
    lines: int
    logs: str
    retrievedAt: str

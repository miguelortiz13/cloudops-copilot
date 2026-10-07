
from fastapi import APIRouter, HTTPException
from typing import Optional
from app.schemas.inventory import *
from app.schemas.k8s import *
from app.schemas.requests import *
from app.core.deps import K8sDep
from app.services.k8s_service import K8sInputError


router = APIRouter(tags=['k8s'])

@router.get("/api/k8s/health", response_model=K8sHealthResponse, tags=["kubernetes"])
def k8s_health(k8s: K8sDep):
    """
    Verifica la conectividad con el clúster Kubernetes configurado.
    Retorna el modo de conexión activo (aks_api | kubeconfig | incluster | offline)
    y la versión del servidor Kubernetes si está disponible.
    """
    try:
        return k8s.health()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/api/k8s/clusters", response_model=K8sClusterListResponse, tags=["kubernetes"])
def k8s_list_clusters(k8s: K8sDep, subscriptionIds: Optional[str] = None):
    """
    Lista todos los clústeres AKS en las suscripciones configuradas,
    consultando Azure Resource Graph. Útil cuando la plataforma
    gestiona múltiples clústeres.
    """
    try:
        sub_ids = [s.strip() for s in subscriptionIds.split(",") if s.strip()] if subscriptionIds else []
        return k8s.list_aks_clusters(sub_ids or None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/api/k8s/incidents", tags=["kubernetes"])
def k8s_incidents(k8s: K8sDep, req: K8sClusterRequest):
    """
    Reporte de incidencias activas del clúster clasificadas por severidad
    (CRITICAL / HIGH / MEDIUM / LOW / INFO).

    Incluye: pods en CrashLoopBackOff/OOMKilled/Pending, nodos NotReady
    o con presión de recursos, workloads degradados, PVCs perdidos,
    servicios sin endpoints, y eventos Warning de alta frecuencia.

    Retorna un Health Score (0-100) del clúster.
    """
    try:
        return k8s.get_incidents(req.model_dump())
    except K8sInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/api/k8s/overview", tags=["kubernetes"])
def k8s_overview(k8s: K8sDep, req: K8sClusterRequest):
    """
    Dashboard completo del clúster: contadores de nodos, pods,
    workloads degradados, PVCs problemáticos, eventos Warning recientes
    y servicios sin endpoints.
    """
    try:
        return k8s.get_overview(req.model_dump())
    except K8sInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/api/k8s/pod-logs", tags=["kubernetes"])
def k8s_pod_logs(
    k8s: K8sDep,
    pod: str,
    namespace: str,
    container: Optional[str] = None,
    tail: int = 100,
):
    """
    Retorna los últimos N líneas de logs de un pod específico.
    Parámetros: pod (nombre), namespace, container (opcional), tail (default 100).
    """
    try:
        return k8s.get_pod_logs(
            pod_name=pod,
            namespace=namespace,
            container=container,
            tail_lines=min(tail, 500),
        )
    except K8sInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/api/k8s/chat", tags=["kubernetes"])
def k8s_chat(k8s: K8sDep, req: K8sChatRequest):
    """
    Chat IA del Agente SRE Kubernetes con contexto real del clúster
    inyectado en Gemini. El agente tiene acceso al estado actual de nodos,
    pods, eventos y workloads para responder con datos reales.
    """
    try:
        return k8s.chat(req.message, req.model_dump())
    except K8sInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/api/k8s/reinit", tags=["kubernetes"])
def k8s_reinit(k8s: K8sDep):
    """
    Fuerza la reinicialización de la conexión al clúster Kubernetes.
    Útil cuando se actualizan las variables de entorno K8S_* sin reiniciar el servicio.
    """
    try:
        k8s._init_client()
        return k8s.health()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




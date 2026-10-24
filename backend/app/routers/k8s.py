
from fastapi import APIRouter, HTTPException
from typing import Optional
from app.schemas.inventory import *
from app.schemas.k8s import *
from app.schemas.requests import *
from app.core.audit import auditado
from app.core.authz import Usuario, requiere
from app.core.deps import AzureDep, K8sDep
from app.llm.limits import exigir_cupo
from app.services import k8s_fleet
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



@router.get("/api/k8s/clusters", tags=["kubernetes"])
def k8s_clusters(azure: AzureDep):
    """Clústeres que reportan con el agente (AKS, EKS o fuera de la nube), con su salud y la antigüedad de su foto."""
    momento = k8s_fleet.ahora()
    salida = []
    for nombre in k8s_fleet.configurados():
        try:
            salida.append(k8s_fleet.resumen(nombre, k8s_fleet.leer(azure.azure_credentials, nombre), momento))
        except k8s_fleet.FotoNoDisponible as exc:
            salida.append({"name": nombre, "reporting": False, "error": str(exc)})
    return {"clusters": salida}


@router.get("/api/k8s/clusters/{nombre}", tags=["kubernetes"])
def k8s_cluster(nombre: str, azure: AzureDep):
    """Detalle de un clúster desde la última foto de su agente: nodos, cargas, pods con problemas, eventos e incidencias."""
    if nombre not in k8s_fleet.configurados():
        raise HTTPException(status_code=404, detail=f"El clúster {nombre!r} no está configurado (kubernetes_clusters).")
    try:
        foto = k8s_fleet.leer(azure.azure_credentials, nombre)
    except k8s_fleet.FotoNoDisponible as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    if foto is None:
        raise HTTPException(status_code=404, detail=f"El agente de {nombre!r} todavía no subió ninguna foto.")
    return k8s_fleet.detalle(nombre, foto, k8s_fleet.ahora())


@router.post("/api/k8s/incidents", tags=["kubernetes"])
def k8s_incidents(k8s: K8sDep, req: K8sClusterRequest, usuario: Usuario = requiere("operador")):
    """
    Reporte de incidencias activas del clúster clasificadas por severidad
    (CRITICAL / HIGH / MEDIUM / LOW / INFO).

    Incluye: pods en CrashLoopBackOff/OOMKilled/Pending, nodos NotReady
    o con presión de recursos, workloads degradados, PVCs perdidos,
    servicios sin endpoints, y eventos Warning de alta frecuencia.

    Retorna un Health Score (0-100) del clúster.
    """
    try:
        with auditado(usuario, "k8s.incidencias", objetivo=req.model_dump().get("cluster_name")):
            return k8s.get_incidents(req.model_dump())
    except K8sInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/api/k8s/overview", tags=["kubernetes"])
def k8s_overview(k8s: K8sDep, req: K8sClusterRequest, usuario: Usuario = requiere("operador")):
    """
    Dashboard completo del clúster: contadores de nodos, pods,
    workloads degradados, PVCs problemáticos, eventos Warning recientes
    y servicios sin endpoints.
    """
    try:
        with auditado(usuario, "k8s.resumen", objetivo=req.model_dump().get("cluster_name")):
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
    usuario: Usuario = requiere("operador"),
):
    """
    Retorna los últimos N líneas de logs de un pod específico.
    Parámetros: pod (nombre), namespace, container (opcional), tail (default 100).
    """
    try:
        with auditado(usuario, "k8s.logs", objetivo=f"{namespace}/{pod}", detalle={"container": container, "tail": min(tail, 500)}):
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
def k8s_chat(k8s: K8sDep, req: K8sChatRequest, usuario: Usuario = requiere("operador")):
    """
    Chat IA del Agente SRE Kubernetes con contexto real del clúster
    inyectado en el modelo de lenguaje. El agente tiene acceso al estado actual
    de nodos, pods, eventos y workloads para responder con datos reales.
    """
    exigir_cupo(usuario.actor)
    try:
        with auditado(usuario, "k8s.chat", detalle={"pregunta": req.message[:300]}):
            return k8s.chat(req.message, req.model_dump(), usuario=usuario.actor)
    except K8sInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/api/k8s/reinit", tags=["kubernetes"])
def k8s_reinit(k8s: K8sDep, usuario: Usuario = requiere("administrador")):
    """
    Fuerza la reinicialización de la conexión al clúster Kubernetes.
    Útil cuando se actualizan las variables de entorno K8S_* sin reiniciar el servicio.
    """
    try:
        with auditado(usuario, "k8s.reiniciar_cliente"):
            k8s._init_client()
            return k8s.health()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




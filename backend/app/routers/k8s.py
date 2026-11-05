"""
Kubernetes: clústeres que reportan con el agente de solo lectura (k8s-agent/).
Todo sale de la última foto de cada uno (app/services/k8s_fleet.py); la
plataforma nunca entra al clúster.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.ai import incidentes
from app.core import ajustes
from app.core.audit import auditado, auditar
from app.core.authz import Usuario, requiere
from app.core.deps import AzureDep
from app.llm.limits import exigir_cupo
from app.services import k8s_chat as k8s_chat_svc
from app.services import k8s_fleet

router = APIRouter(tags=["kubernetes"])


class K8sChatRequest(BaseModel):
    message: str = Field(max_length=4000)
    clusterName: Optional[str] = None


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


@router.post("/api/k8s/chat", tags=["kubernetes"])
def k8s_chat(req: K8sChatRequest, azure: AzureDep, usuario: Usuario = requiere("operador")):
    """
    Chat del agente SRE sobre la última foto del clúster (incidencias, pods con
    problemas y sus logs, cargas, nodos y eventos). `clusterName` elige el
    clúster; sin él, el que nombre la pregunta o el primero que reporta.
    """
    exigir_cupo(usuario.actor)
    momento = k8s_fleet.ahora()
    fotos = {}
    for nombre in k8s_fleet.configurados():
        try:
            fotos[nombre] = k8s_fleet.leer(azure.azure_credentials, nombre)
        except k8s_fleet.FotoNoDisponible as exc:
            raise HTTPException(status_code=503, detail=str(exc))
    elegido = k8s_chat_svc.elegir(req.message, req.clusterName,
                                  [k8s_fleet.resumen(n, f, momento) for n, f in fotos.items()])
    if not elegido:
        return {"answer": "No hay clústeres que reporten con el agente. Conecta uno desde la página Kubernetes.",
                "mode": "rules", "context_summary": None}
    with auditado(usuario, "k8s.chat", objetivo=elegido, detalle={"pregunta": req.message[:300]}):
        return k8s_chat_svc.responder(req.message, k8s_fleet.detalle(elegido, fotos[elegido], momento), usuario.actor)


def _configurado(nombre: str) -> None:
    if nombre not in k8s_fleet.configurados():
        raise HTTPException(status_code=404, detail=f"El clúster {nombre!r} no está configurado (kubernetes_clusters).")


class AbrirIncidente(BaseModel):
    resource: str = Field(max_length=300)
    namespace: Optional[str] = Field(default=None, max_length=100)


@router.post("/api/k8s/clusters/{nombre}/incidents", status_code=201, tags=["kubernetes"])
def abrir_incidente(nombre: str, body: AbrirIncidente, tareas: BackgroundTasks, azure: AzureDep,
                    usuario: Usuario = requiere("operador")):
    """Abre un incidente con diagnóstico de IA desde una incidencia de la foto actual (si sigue ahí)."""
    _configurado(nombre)
    try:
        foto = k8s_fleet.leer(azure.azure_credentials, nombre)
    except k8s_fleet.FotoNoDisponible as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    i = next((x for x in k8s_fleet.incidencias(foto or {}, k8s_fleet.ahora(), nombre)
              if x["resource"] == body.resource and x["namespace"] == body.namespace), None)
    if i is None:
        raise HTTPException(status_code=404, detail="Esa incidencia ya no está en la última foto.")
    incidente, accion = incidentes.abrir_desde_kubernetes(nombre, i, usuario.actor)
    if accion == "nuevo":
        tareas.add_task(incidentes.diagnosticar, incidente, azure.azure_credentials)
        auditar(usuario, "incidente.abrir", objetivo=str(incidente), detalle={"cluster": nombre, "resource": body.resource})
    return {"incident": incidente, "action": accion}


@router.get("/api/settings/k8s/{nombre}", tags=["kubernetes"])
def ver_ajustes(nombre: str):
    _configurado(nombre)
    return {"values": ajustes.cluster(nombre), "defaults": ajustes.CLUSTER, "limits": ajustes.LIMITES}


@router.put("/api/settings/k8s/{nombre}", tags=["kubernetes"])
def cambiar_ajustes(nombre: str, body: Dict[str, Any], usuario: Usuario = requiere("administrador")):
    """Namespaces ignorados, umbrales de reinicios y de gracia, y si el clúster avisa (y de qué severidades)."""
    _configurado(nombre)
    try:
        valores = ajustes.guardar_cluster(nombre, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    auditar(usuario, "ajustes.kubernetes", objetivo=nombre, detalle=body)
    return {"values": valores}

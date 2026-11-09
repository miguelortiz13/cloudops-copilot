"""
Herramientas del perfil `asistente` (etapa A): funciones de solo lectura sobre lo
que la plataforma ya guarda. Leen las mismas vistas que el panel (con su caché,
app/readmodel) y las fotos de Kubernetes; no consultan la nube.

Cada resultado trae `enlace` (la vista del panel que lo respalda, para citarla) y
las listas viajan acotadas: `muestra`, `total`, `truncado`.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.ai.agente import Herramienta
from app.readmodel import service
from app.services import k8s_chat, k8s_fleet

MUESTRA = 20
NUBES = ["azure", "aws", "kubernetes"]


def _acotar(items: List[Dict[str, Any]], limite: int) -> Dict[str, Any]:
    limite = max(1, min(int(limite or MUESTRA), 50))
    return {"muestra": items[:limite], "total": len(items), "truncado": len(items) > limite}


def _contiene(valor: Optional[str], buscado: Optional[str]) -> bool:
    return not buscado or (buscado.lower() in (valor or "").lower())


CAMPOS_RECURSO = ("name", "provider", "account", "type", "region", "group", "cost_30d", "in_iac", "created_by", "first_seen")


def buscar_recursos(texto: Optional[str] = None, nube: Optional[str] = None, tipo: Optional[str] = None,
                    cuenta: Optional[str] = None, en_terraform: Optional[bool] = None,
                    creado_por: Optional[str] = None, limite: int = MUESTRA) -> Dict[str, Any]:
    datos = service.inventario_multinube()
    items = [{k: r.get(k) for k in CAMPOS_RECURSO} for r in datos["resources"]
             if (_contiene(r["name"], texto) or _contiene(r["uid"], texto))
             and (not nube or r["provider"] == nube)
             and (_contiene(r["type"], tipo) or _contiene(r.get("native_type"), tipo))
             and _contiene(r.get("account"), cuenta)
             and (en_terraform is None or r.get("in_iac") is en_terraform)
             and _contiene(r.get("created_by"), creado_por)]
    items.sort(key=lambda r: -(r["cost_30d"] or 0))
    return {**_acotar(items, limite), "gasto_30d_de_los_encontrados": round(sum(r["cost_30d"] or 0 for r in items), 2),
            "enlace": "#/activos/inventario",
            "nota": "in_iac: true en Terraform, false fuera, null sin estados para saberlo."}


def recursos_nuevos(dias: int = 7, solo_fuera_de_terraform: bool = False, limite: int = MUESTRA) -> Dict[str, Any]:
    desde = datetime.now(timezone.utc) - timedelta(days=max(1, min(int(dias), 90)))
    items = [{k: r.get(k) for k in CAMPOS_RECURSO} for r in service.inventario_multinube()["resources"]
             if r.get("first_seen") and datetime.fromisoformat(r["first_seen"]) >= desde
             and (not solo_fuera_de_terraform or r.get("in_iac") is False)]
    items.sort(key=lambda r: r["first_seen"], reverse=True)
    return {**_acotar(items, limite), "desde": desde.date().isoformat(), "enlace": "#/activos/inventario",
            "nota": "created_by solo existe si el registro de actividad mostró que lo creó una persona."}


def hallazgos(severidad: Optional[str] = None, estado: str = "activos", nube: Optional[str] = None,
              texto: Optional[str] = None, limite: int = MUESTRA) -> Dict[str, Any]:
    todos = service.hallazgos()["items"]
    elegidos = [h for h in todos
                if (estado == "todos" or (h["status"] != "resuelto" if estado == "activos" else h["status"] == estado))
                and (not severidad or h["severity"] == severidad)
                and (not nube or h["account_uid"].split(":", 1)[0] == nube)
                and (_contiene(h["title"], texto) or _contiene(h["resource_name"], texto) or _contiene(h["rule_id"], texto))]
    por_severidad: Dict[str, int] = {}
    for h in elegidos:
        por_severidad[h["severity"]] = por_severidad.get(h["severity"], 0) + 1
    campos = ("severity", "status", "title", "rule_id", "resource_name", "account", "remediation", "accepted_until", "first_seen")
    return {**_acotar([{k: h.get(k) for k in campos} for h in elegidos], limite), "por_severidad": por_severidad,
            "enlace": "#/riesgo/hallazgos"}


def costos(periodo: str = "30d", nube: Optional[str] = None) -> Dict[str, Any]:
    cuentas = None
    if nube:
        cuentas = [a["uid"] for a in service.cuentas()["accounts"] if a["provider"] == nube] or ["-"]
    c = service.costos(periodo, cuentas)
    if not c.get("available"):
        return {"error": c.get("message", "Sin costos recolectados."), "enlace": "#/costos/historial"}

    def top(clave, campos):
        return [{k: x.get(k) for k in campos} for x in c[clave][:10]]

    return {"periodo": c["label"], "desde": c["from"], "hasta": c["to"], "moneda": c["currency"], "total": c["total"],
            "periodo_anterior": c["previous_total"], "variacion_pct": c["delta_percentage"],
            "por_cuenta": top("by_account", ("name", "cost", "share")), "por_servicio": top("by_service", ("key", "cost", "share")),
            "por_recurso": top("by_resource", ("name", "cost", "account", "type")), "datos_hasta": c["data_through"],
            "enlace": "#/costos/historial"}


def cumplimiento() -> Dict[str, Any]:
    c = service.cumplimiento()
    return {"marcos": [{"marco": f"{m['name']} {m['version']}", "resumen": m["summary"],
                        "no_cumplen": [{"control": x["id"], "titulo": x["title"], "hallazgos_activos": x["active"]}
                                       for x in m["controls"] if x["status"] == "no_cumple"]}
                       for m in c["frameworks"]],
            "enlace": "#/riesgo/cumplimiento"}


MAX_INCIDENCIAS, MAX_PODS, MAX_EVENTOS, MAX_LINEAS = 20, 6, 20, 15


def enfocar(foto: Dict[str, Any], d: Dict[str, Any], namespace: Optional[str], objeto: Optional[str]) -> Dict[str, Any]:
    """
    El contexto del clúster acotado para un modelo. En un clúster real el detalle
    completo (decenas de pods, eventos e incidencias) no entra; con `namespace` y
    `objeto` (pod, deployment o servicio de la alerta) queda solo lo que importa,
    y los eventos salen de los 200 de la foto, no de los más recientes.
    """
    def coincide(ns: Optional[str], *nombres: Optional[str]) -> bool:
        return (not namespace or ns == namespace) and (not objeto or any(objeto in (n or "") for n in nombres))

    ctx = k8s_chat.contexto(d)
    incid = [i for i in ctx["incidencias"] if coincide(i["namespace"], i["resource"], i["title"])
             or (i["category"] == "nodo" and not objeto)]
    pods = [p for p in ctx["pods_con_problemas"] if coincide(p["namespace"], p["name"], p.get("owner"))]
    for p in pods:
        if p.get("log"):
            p["log"] = {**p["log"], "lines": p["log"]["lines"][-MAX_LINEAS:]}
    eventos = [e for e in foto.get("events", []) if coincide(e.get("namespace"), e.get("name"))]
    cargas = [w for w in ctx["cargas_degradadas"] if coincide(w["namespace"], w["name"])]
    return {**{k: ctx[k] for k in ("cluster", "distribucion", "version", "foto_tomada", "foto_vieja", "salud",
                                   "nodos_listos", "pods_en_ejecucion", "nodos")},
            "filtro": {"namespace": namespace, "objeto": objeto},
            "incidencias": _acotar(incid, MAX_INCIDENCIAS), "pods_con_problemas": _acotar(pods, MAX_PODS),
            "cargas_degradadas": _acotar(cargas, MAX_INCIDENCIAS), "eventos": _acotar(eventos, MAX_EVENTOS)}


def para_asistente(credenciales) -> List[Herramienta]:
    """Herramientas del chat del panel. `credenciales`: las del API, para leer las fotos de Kubernetes."""

    def clusters_kubernetes() -> Dict[str, Any]:
        momento = k8s_fleet.ahora()
        salida = []
        for nombre in k8s_fleet.configurados():
            r = k8s_fleet.resumen(nombre, k8s_fleet.leer(credenciales, nombre), momento)
            salida.append({k: r.get(k) for k in ("name", "reporting", "distribution", "version", "support", "stale",
                                                  "nodes", "nodes_ready", "pods", "pods_running", "health", "incidents")})
        return {"clusters": salida, "enlace": "#/activos/kubernetes"}

    def estado_cluster(nombre: str, namespace: Optional[str] = None, objeto: Optional[str] = None) -> Dict[str, Any]:
        if nombre not in k8s_fleet.configurados():
            return {"error": f"No hay un clúster llamado {nombre!r}.", "clusters": k8s_fleet.configurados()}
        foto = k8s_fleet.leer(credenciales, nombre)
        if foto is None:
            return {"error": f"El agente de {nombre} todavía no envió ninguna foto."}
        return {**enfocar(foto, k8s_fleet.detalle(nombre, foto, k8s_fleet.ahora()), namespace, objeto),
                "enlace": f"#/activos/kubernetes/{nombre}"}

    def cambios_recientes(horas: int = 24, cluster: Optional[str] = None, namespace: Optional[str] = None,
                          objeto: Optional[str] = None) -> Dict[str, Any]:
        horas = max(1, min(int(horas), 48))
        desde = datetime.now(timezone.utc) - timedelta(hours=horas)
        despliegues, sin_dato = [], []
        for nombre in ([cluster] if cluster else k8s_fleet.configurados()):
            foto = k8s_fleet.leer(credenciales, nombre) if nombre in k8s_fleet.configurados() else None
            if foto is None or foto.get("deployments_recent") is None:
                sin_dato.append(nombre)
                continue
            for d in foto["deployments_recent"]:
                nueva, *antes = d["revisiones"]
                if (not nueva["created"] or datetime.fromisoformat(nueva["created"].replace("Z", "+00:00")) < desde
                        or (namespace and d["namespace"] != namespace) or (objeto and objeto not in d["deployment"])):
                    continue
                previas = antes[0]["images"] if antes else []
                despliegues.append({
                    "cluster": nombre, "namespace": d["namespace"], "deployment": d["deployment"],
                    "revision": nueva["revision"], "hora": nueva["created"], "listas": f"{nueva['ready']}/{nueva['replicas']}",
                    "revision_anterior": antes[0]["revision"] if antes else None,
                    "cambio_de_imagen": [f"{a} -> {b}" for a, b in zip(previas, nueva["images"]) if a != b],
                    "imagenes": nueva["images"]})
        try:
            nuevos = [{k: r.get(k) for k in ("name", "provider", "account", "type", "created_by", "first_seen", "in_iac")}
                      for r in service.inventario_multinube()["resources"]
                      if r.get("first_seen") and datetime.fromisoformat(r["first_seen"]) >= desde
                      and (not namespace or r.get("group") == namespace)]
        except Exception as exc:  # sin base el inventario no está; los despliegues sí
            nuevos = [{"error": f"Inventario no disponible: {type(exc).__name__}"}]
        return {"desde": desde.isoformat(timespec="minutes"),
                "despliegues_kubernetes": _acotar(sorted(despliegues, key=lambda x: x["hora"], reverse=True), MUESTRA),
                "recursos_nuevos": _acotar(nuevos, MUESTRA),
                "sin_historial_de_despliegues": sin_dato, "enlace": f"#/activos/kubernetes/{cluster}" if cluster else "#/activos/kubernetes",
                "nota": "Un despliegue es una revisión nueva de un Deployment (su ReplicaSet). Compara su hora con el "
                        "inicio de la alerta: un cambio minutos antes es el primer sospechoso."}

    def incidentes(estado: Optional[str] = None, severidad: Optional[str] = None, cluster: Optional[str] = None,
                   dias: int = 30, limite: int = MUESTRA) -> Dict[str, Any]:
        from app.routers import incidents  # shortcut: reusa la ruta del panel; mover a un servicio si crece

        r = incidents.listar(estado=estado, severidad=severidad, cluster=cluster, dias=max(1, min(int(dias), 365)), agrupados=False)
        if not r["configured"]:
            return {"error": "Sin base de datos no hay incidentes."}
        return {**_acotar(r["items"], limite), "enlace": "#/operacion/incidentes"}

    def incidente(id: int) -> Dict[str, Any]:
        from fastapi import HTTPException

        from app.routers import incidents

        try:
            d = incidents.detalle(int(id))
        except HTTPException as exc:
            return {"error": exc.detail}
        return {**{k: v for k, v in d.items() if k != "alert_list"}, "alertas": d["alert_list"][:10],
                "events": d["events"][-40:], "enlace": f"#/operacion/incidentes/{d['id']}"}

    def buscar_conocimiento(consulta: str, tipo: Optional[str] = None, limite: int = 5) -> Dict[str, Any]:
        from app.ai import conocimiento

        r = conocimiento.buscar(consulta, tipo, max(1, min(int(limite), 8)))
        return {**r, "nota": "Cita cada dato con su fuente: el enlace del panel si lo trae, o la fuente (runbook o guía)."}

    texto = {"type": "string"}
    return [
        Herramienta("buscar_recursos",
                    "Busca recursos del inventario de todas las nubes (Azure, AWS y clústeres de Kubernetes) por nombre, "
                    "nube, tipo, cuenta, si están en Terraform o quién los creó. Ordena por gasto de 30 días.",
                    {"type": "object", "properties": {
                        "texto": {**texto, "description": "Parte del nombre o del identificador"},
                        "nube": {"type": "string", "enum": NUBES}, "tipo": {**texto, "description": "Ej.: storage, vm, bucket, Deployment"},
                        "cuenta": {**texto, "description": "Parte del nombre de la suscripción, cuenta o clúster"},
                        "en_terraform": {"type": "boolean"}, "creado_por": texto, "limite": {"type": "integer"}}},
                    buscar_recursos),
        Herramienta("recursos_nuevos",
                    "Recursos que aparecieron en los últimos N días, con quién los creó; opcionalmente solo los que están "
                    "fuera de Terraform.",
                    {"type": "object", "properties": {"dias": {"type": "integer"}, "solo_fuera_de_terraform": {"type": "boolean"},
                                                      "limite": {"type": "integer"}}},
                    recursos_nuevos),
        Herramienta("hallazgos",
                    "Hallazgos de seguridad y de recursos sin uso de todas las nubes, con su estado y remediación. estado: "
                    "activos (no resueltos, por defecto), abierto, asumido, aceptado, resuelto o todos.",
                    {"type": "object", "properties": {
                        "severidad": {"type": "string", "enum": ["critica", "alta", "media"]},
                        "estado": {"type": "string", "enum": ["activos", "abierto", "asumido", "aceptado", "resuelto", "todos"]},
                        "nube": {"type": "string", "enum": NUBES}, "texto": texto, "limite": {"type": "integer"}}},
                    hallazgos),
        Herramienta("costos",
                    "Gasto real por periodo: total, comparación con el periodo anterior y los que más gastan por cuenta, "
                    "servicio y recurso. periodo: 7d, 30d, 90d, mtd (mes en curso) o last_month.",
                    {"type": "object", "properties": {"periodo": {"type": "string", "enum": ["7d", "30d", "90d", "mtd", "last_month"]},
                                                      "nube": {"type": "string", "enum": ["azure", "aws"]}}},
                    costos),
        Herramienta("cumplimiento", "Estado de los controles de CIS (Azure, AWS, Kubernetes) e ISO 27001 y cuáles no cumplen.",
                    {"type": "object", "properties": {}}, cumplimiento),
        Herramienta("clusters_kubernetes", "Clústeres de Kubernetes conectados con su salud, versión y fin de soporte.",
                    {"type": "object", "properties": {}}, clusters_kubernetes),
        Herramienta("cambios_recientes",
                    "Qué cambió en las últimas N horas (hasta 48): despliegues de Kubernetes (revisión nueva de cada "
                    "Deployment, su hora y qué imagen cambió) y recursos nuevos del inventario. Filtra por clúster, "
                    "namespace y objeto (parte del nombre del deployment).",
                    {"type": "object", "properties": {"horas": {"type": "integer"}, "cluster": texto, "namespace": texto,
                                                      "objeto": texto}},
                    cambios_recientes),
        Herramienta("estado_cluster",
                    "Detalle de un clúster de Kubernetes desde la última foto de su agente: incidencias, pods con problemas "
                    "y sus últimas líneas de log, cargas degradadas, nodos y eventos. Para investigar algo puntual (una "
                    "alerta, un servicio), pasa namespace y objeto (parte del nombre del pod, deployment o servicio): "
                    "trae solo lo que coincide, incluidos sus eventos.",
                    {"type": "object", "properties": {"nombre": texto, "namespace": texto,
                                                      "objeto": {**texto, "description": "Parte del nombre del pod, deployment o servicio"}},
                     "required": ["nombre"]}, estado_cluster),
        Herramienta("incidentes",
                    "Incidentes de los últimos N días (por defecto 30), los más recientes primero, con su severidad, "
                    "estado, clúster, responsable y si el diagnóstico está listo. estado: vivos (sin resolver ni cerrar), "
                    "abierto, reconocido, en_curso, resuelto o cerrado.",
                    {"type": "object", "properties": {
                        "estado": {"type": "string", "enum": ["vivos", "abierto", "reconocido", "en_curso", "resuelto", "cerrado"]},
                        "severidad": {"type": "string", "enum": ["critica", "alta", "media"]}, "cluster": texto,
                        "dias": {"type": "integer"}, "limite": {"type": "integer"}}},
                    incidentes),
        Herramienta("incidente",
                    "Detalle de un incidente por su número: alertas, diagnóstico del agente, post-mortem, incidentes de su "
                    "tormenta y línea de tiempo (quién hizo qué y cuándo).",
                    {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}, incidente),
        Herramienta("buscar_conocimiento",
                    "Busca en la base de conocimiento: runbooks (cómo diagnosticar y resolver un tipo de problema), la guía "
                    "de uso del panel (cómo se hace algo aquí), el catálogo de controles (riesgo y remediación de cada regla), "
                    "incidentes ya resueltos con su diagnóstico y lo que se hizo, y excepciones de control aprobadas. Usa la "
                    "consulta con los términos del problema (alerta, motivo, mensaje de error, servicio).",
                    {"type": "object", "properties": {
                        "consulta": {**texto, "description": "Qué buscar, por ejemplo 'CrashLoopBackOff connection refused redis'"},
                        "tipo": {"type": "string", "enum": ["runbook", "guia", "control", "incidente", "excepcion"]},
                        "limite": {"type": "integer"}}, "required": ["consulta"]},
                    buscar_conocimiento),
    ]

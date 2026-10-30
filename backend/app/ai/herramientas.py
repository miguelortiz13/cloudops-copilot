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
            "enlace": "#/inventario",
            "nota": "in_iac: true en Terraform, false fuera, null sin estados para saberlo."}


def recursos_nuevos(dias: int = 7, solo_fuera_de_terraform: bool = False, limite: int = MUESTRA) -> Dict[str, Any]:
    desde = datetime.now(timezone.utc) - timedelta(days=max(1, min(int(dias), 90)))
    items = [{k: r.get(k) for k in CAMPOS_RECURSO} for r in service.inventario_multinube()["resources"]
             if r.get("first_seen") and datetime.fromisoformat(r["first_seen"]) >= desde
             and (not solo_fuera_de_terraform or r.get("in_iac") is False)]
    items.sort(key=lambda r: r["first_seen"], reverse=True)
    return {**_acotar(items, limite), "desde": desde.date().isoformat(), "enlace": "#/inventario",
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
            "enlace": "#/secops/gestion"}


def costos(periodo: str = "30d", nube: Optional[str] = None) -> Dict[str, Any]:
    cuentas = None
    if nube:
        cuentas = [a["uid"] for a in service.cuentas()["accounts"] if a["provider"] == nube] or ["-"]
    c = service.costos(periodo, cuentas)
    if not c.get("available"):
        return {"error": c.get("message", "Sin costos recolectados."), "enlace": "#/finops/historial"}

    def top(clave, campos):
        return [{k: x.get(k) for k in campos} for x in c[clave][:10]]

    return {"periodo": c["label"], "desde": c["from"], "hasta": c["to"], "moneda": c["currency"], "total": c["total"],
            "periodo_anterior": c["previous_total"], "variacion_pct": c["delta_percentage"],
            "por_cuenta": top("by_account", ("name", "cost", "share")), "por_servicio": top("by_service", ("key", "cost", "share")),
            "por_recurso": top("by_resource", ("name", "cost", "account", "type")), "datos_hasta": c["data_through"],
            "enlace": "#/finops/historial"}


def cumplimiento() -> Dict[str, Any]:
    c = service.cumplimiento()
    return {"marcos": [{"marco": f"{m['name']} {m['version']}", "resumen": m["summary"],
                        "no_cumplen": [{"control": x["id"], "titulo": x["title"], "hallazgos_activos": x["active"]}
                                       for x in m["controls"] if x["status"] == "no_cumple"]}
                       for m in c["frameworks"]],
            "enlace": "#/cumplimiento/controles"}


def para_asistente(credenciales) -> List[Herramienta]:
    """Herramientas del chat del panel. `credenciales`: las del API, para leer las fotos de Kubernetes."""

    def clusters_kubernetes() -> Dict[str, Any]:
        momento = k8s_fleet.ahora()
        salida = []
        for nombre in k8s_fleet.configurados():
            r = k8s_fleet.resumen(nombre, k8s_fleet.leer(credenciales, nombre), momento)
            salida.append({k: r.get(k) for k in ("name", "reporting", "distribution", "version", "support", "stale",
                                                  "nodes", "nodes_ready", "pods", "pods_running", "health", "incidents")})
        return {"clusters": salida, "enlace": "#/kubernetes"}

    def estado_cluster(nombre: str) -> Dict[str, Any]:
        if nombre not in k8s_fleet.configurados():
            return {"error": f"No hay un clúster llamado {nombre!r}.", "clusters": k8s_fleet.configurados()}
        foto = k8s_fleet.leer(credenciales, nombre)
        if foto is None:
            return {"error": f"El agente de {nombre} todavía no envió ninguna foto."}
        return {**k8s_chat.contexto(k8s_fleet.detalle(nombre, foto, k8s_fleet.ahora())), "enlace": f"#/kubernetes/{nombre}"}

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
        Herramienta("estado_cluster",
                    "Detalle de un clúster de Kubernetes desde la última foto de su agente: incidencias, pods con problemas "
                    "y sus últimas líneas de log, cargas degradadas, nodos y eventos.",
                    {"type": "object", "properties": {"nombre": texto}, "required": ["nombre"]}, estado_cluster),
    ]

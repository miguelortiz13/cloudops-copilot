"""
Quién creó cada recurso de AWS, desde el historial de eventos de CloudTrail
(LookupEvents: 90 días de eventos de gestión, sin trail y sin costo).

Muchos eventos de creación no traen el ARN del recurso (CreateWorkGroup solo
trae el nombre en los parámetros): se cruza con el inventario por ARN, nombre
o id, dentro del mismo servicio del evento.

Persona: usuario de Identity Center, usuario IAM o root, sin un servicio de
AWS de por medio ni Terraform en el user agent. El resto es automatización.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from app.providers.base import Creacion, Recurso

DIAS = 90  # lo que conserva el historial de eventos
PREFIJOS = ("Create", "Run", "Allocate", "Register", "Import")
AUTOMATIZACION = ("terraform", "hashicorp", "cloudformation", "aws-cdk", "pulumi")
# shortcut: tope de páginas por región (50 eventos cada una); en cuentas con mucha actividad conviene un trail a S3.
MAX_PAGINAS = 200


def _servicio(arn: str) -> str:
    return arn.split(":", 3)[2]


def indice(recursos: Iterable[Recurso]) -> Dict[Tuple[str, str], str]:
    """(servicio, ARN | nombre | id) -> uid."""
    claves: Dict[Tuple[str, str], str] = {}
    for r in recursos:
        servicio = _servicio(r.native_id)
        for clave in {r.native_id, r.name, r.native_id.rsplit("/", 1)[-1]}:
            claves.setdefault((servicio, clave), r.uid)
    return claves


def _valores(dato: Any, profundidad: int = 0) -> Iterable[str]:
    """Textos dentro de los parámetros y la respuesta del evento."""
    if profundidad > 4:
        return
    if isinstance(dato, str):
        yield dato
    elif isinstance(dato, dict):
        for v in dato.values():
            yield from _valores(v, profundidad + 1)
    elif isinstance(dato, list):
        for v in dato[:20]:
            yield from _valores(v, profundidad + 1)


def actor(evento: Dict[str, Any]) -> Tuple[Optional[str], bool]:
    """(quién, si es una persona)."""
    u = evento.get("userIdentity") or {}
    tipo = u.get("type")
    automatizado = bool(u.get("invokedBy")) or any(a in (evento.get("userAgent") or "").lower() for a in AUTOMATIZACION)
    emisor = ((u.get("sessionContext") or {}).get("sessionIssuer") or {}).get("arn", "")
    if tipo == "Root":
        return "root", not automatizado
    if tipo == "IAMUser":
        return u.get("userName"), not automatizado
    if tipo == "AssumedRole":
        sesion = (u.get("arn") or "").rsplit("/", 1)[-1] or None
        return sesion, "/aws-reserved/sso.amazonaws.com/" in emisor and not automatizado
    return u.get("invokedBy") or u.get("principalId"), False


def creaciones(cliente: Callable[..., Any], recursos: List[Recurso], ahora: Optional[datetime] = None
               ) -> Tuple[List[Creacion], datetime, datetime]:
    hasta = ahora or datetime.now(timezone.utc)
    desde = hasta - timedelta(days=DIAS)
    claves = indice(recursos)
    regiones: Set[str] = {r.region for r in recursos if r.region} | {"us-east-1"}  # IAM y S3 se registran ahí
    encontradas: Dict[str, Creacion] = {}
    for region in sorted(regiones):
        paginas = cliente("cloudtrail", region_name=region).get_paginator("lookup_events").paginate(
            LookupAttributes=[{"AttributeKey": "ReadOnly", "AttributeValue": "false"}], StartTime=desde, EndTime=hasta,
            PaginationConfig={"MaxItems": MAX_PAGINAS * 50, "PageSize": 50})
        for pagina in paginas:
            for e in pagina.get("Events") or []:
                if not (e.get("EventName") or "").startswith(PREFIJOS):
                    continue
                evento = json.loads(e.get("CloudTrailEvent") or "{}")
                if evento.get("errorCode"):
                    continue  # la creación falló
                servicio = (evento.get("eventSource") or "").split(".", 1)[0]
                candidatos = [r.get("ARN") or r.get("resourceName") for r in evento.get("resources") or []]
                candidatos += list(_valores(evento.get("responseElements"))) + list(_valores(evento.get("requestParameters")))
                uid = next((claves[(servicio, c)] for c in candidatos if c and (servicio, c) in claves), None)
                if uid is None or uid in encontradas:
                    continue
                quien, persona = actor(evento)
                if quien:
                    momento = e.get("EventTime")
                    if isinstance(momento, str):
                        momento = datetime.fromisoformat(momento)
                    encontradas[uid] = Creacion(uid, quien, momento, persona)
    return list(encontradas.values()), desde, hasta

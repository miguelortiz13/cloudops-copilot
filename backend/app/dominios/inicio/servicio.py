"""
Dominio Inicio (fase 5 del plan 10): *Mis pendientes* y *Qué cambió*.

- **Mis pendientes** lee el contrato común de gestión (estado y responsable) de incidentes, hallazgos y
  alertas de costo, más lo que vence pronto (riesgos aceptados, excepciones de control, silencios). Cada
  pendiente trae el porqué y una urgencia de 0 a 3 para ordenarlos.
- **Qué cambió** cuenta lo nuevo desde un momento (la última visita, que recuerda el panel).
"""

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import false, func, or_, select

from app.ai.incidentes import ABIERTOS
from app.ai import guardas
from app.core import ajustes, config
from app.db import engine as db
from app.db.models import ControlException, CostEvent, Finding, Incident, IncidentAction, Resource, Rule

URGENCIA = {"critica": 3, "alta": 2, "media": 1}
PRONTO = timedelta(days=14)
# Fase 7 (plan 12): lo que cierra el ciclo del incidente mira las últimas dos semanas.
CICLO = timedelta(days=14)
MAX_SUELTOS = 3  # más diagnósticos sin marcar que esto van en un solo pendiente


def _dueno(tags: Optional[Dict[str, Any]]) -> Optional[str]:
    """El valor de la tag Owner del recurso (sin importar mayúsculas en el nombre de la tag)."""
    return next((str(v) for k, v in (tags or {}).items() if k.lower() == "owner"), None)


def _yo(valor: Optional[str], actor: str) -> bool:
    return bool(valor) and valor.strip().lower() == actor.strip().lower()


def pendientes(actor: str, ahora: Optional[datetime] = None) -> List[Dict[str, Any]]:
    ahora = ahora or datetime.now(timezone.utc)
    hoy, items = ahora.date(), []

    def agregar(tipo, titulo, porque, urgencia, enlace, cuando=None, detalle=None):
        items.append({"type": tipo, "title": titulo, "why": porque, "urgency": urgencia, "link": enlace,
                      "when": cuando.isoformat() if cuando else None, "detail": (detalle or "")[:400] or None})

    with db.session_scope() as s:
        for i in s.scalars(select(Incident).where(Incident.status.in_(ABIERTOS), Incident.parent_id.is_(None))):
            detalle = i.diagnosis or "; ".join(str(a.get("summary") or a.get("name")) for a in (i.alerts or [])[:3])
            if _yo(i.assignee, actor):
                agregar("incidente", f"#{i.id} {i.title}", f"Asignado a ti · {i.status.replace('_', ' ')}", URGENCIA.get(i.severity, 1),
                        f"#/operacion/incidentes/{i.id}", i.opened_at, detalle)
            elif not i.assignee and i.severity in ("critica", "alta"):
                agregar("incidente", f"#{i.id} {i.title}", f"Severidad {i.severity} y sin responsable", URGENCIA[i.severity],
                        f"#/operacion/incidentes/{i.id}", i.opened_at, detalle)

        filas = s.execute(select(Finding, Rule.title, Resource.name, Rule.remediation, Resource.tags).join(Rule, Rule.id == Finding.rule_id)
                          .outerjoin(Resource, Resource.uid == Finding.resource_uid)
                          .where(Finding.status != "resuelto"))
        for f, regla, recurso, remediacion, tags in filas:
            titulo = f"{regla} · {recurso or f.resource_uid.rsplit('/', 1)[-1]}"
            if f.status == "aceptado" and f.accepted_until and f.accepted_until - hoy <= PRONTO:
                vence = (f.accepted_until - hoy).days
                agregar("hallazgo", titulo, "Riesgo aceptado vencido" if vence < 0 else f"Riesgo aceptado: vence en {vence} día(s)",
                        2 if vence <= 3 else 1, "#/riesgo/hallazgos", detalle=remediacion)
            elif f.status in ("abierto", "asumido") and _yo(f.owner, actor):
                atrasado = f.due_date is not None and f.due_date < hoy
                agregar("hallazgo", titulo, f"Asignado a ti · vencido el {f.due_date.isoformat()}" if atrasado else
                        f"Asignado a ti{f' · vence el {f.due_date.isoformat()}' if f.due_date else ''}",
                        min(3, URGENCIA.get(f.severity, 1) + atrasado), "#/riesgo/hallazgos", detalle=remediacion)
            elif f.status == "abierto" and not f.owner and _yo(_dueno(tags), actor):
                agregar("hallazgo", titulo, "Sin responsable; el recurso tiene tu correo en la tag Owner",
                        URGENCIA.get(f.severity, 1), "#/riesgo/hallazgos", detalle=remediacion)

        for e in s.scalars(select(CostEvent).where(CostEvent.status.in_(("abierto", "reconocido")))):
            if _yo(e.assignee, actor) or not e.assignee:
                agregar("costo", e.title, "Asignada a ti" if e.assignee else "Alerta de costo sin responsable",
                        2 if e.kind == "presupuesto" else 1, "#/costos/alertas", e.opened_at, e.explanation)

        for x in s.scalars(select(ControlException).where(ControlException.revoked_at.is_(None))):
            if x.until - hoy <= PRONTO and x.until >= hoy:
                agregar("excepcion", f"Excepción {x.framework} {x.control}", f"Vence en {(x.until - hoy).days} día(s): renovar o corregir",
                        1, "#/riesgo/cumplimiento")

        _cerrar_el_ciclo(s, actor, ahora, agregar)

    for sil in ajustes.silencios(ahora):
        hasta = datetime.fromisoformat(sil["hasta"])
        if _yo(sil.get("creado_por"), actor) and hasta - ahora <= timedelta(hours=24):
            alcance = " · ".join(str(sil[k]) for k in ("cluster", "namespace", "alerta", "objeto") if sil.get(k))
            agregar("silencio", f"Silencio {alcance}", "Vence en menos de 24 h: lo que calla vuelve a avisar", 1, "#/operacion/silencios", hasta)

    return sorted(items, key=lambda x: (-x["urgency"], x["when"] or ""))


SISTEMA = (
    "Eres el asistente de operaciones cloud de {org}. Recibes los pendientes de una persona, ya ordenados por urgencia "
    "con reglas, cada uno con su porqué, su enlace y a veces un detalle (diagnóstico, remediación o explicación). Ayúdala "
    "a decidir por dónde empezar. Responde en español, en Markdown, en menos de 900 caracteres:\n"
    "**Por dónde empezar:** 1 a 3 viñetas; cada una dice la acción concreta (reconocer y revisar el diagnóstico, cerrar "
    "como ruido, asignar, renovar o corregir), cita el pendiente con su enlace en Markdown ([#31](#/operacion/incidentes/31)) "
    "y por qué va antes. Si varios pendientes son la misma causa (el mismo clúster y servicio casi a la vez), agrúpalos "
    "en una viñeta.\n**Puede esperar:** una línea con lo demás.\n"
    "Usa solo los datos recibidos: no inventes cifras, fechas ni causas. Si no hay pendientes urgentes, dilo en una línea."
)
_CACHE: Dict[str, Any] = {}
CACHE_SEGUNDOS = 1800


def priorizar(actor: str, items: List[Dict[str, Any]], cobrar=lambda: None) -> Dict[str, Any]:
    """
    La IA propone por dónde empezar. Se recuerda 30 minutos mientras los pendientes no cambien (cuesta tokens);
    `cobrar` descuenta el cupo del usuario solo cuando de verdad se llama al modelo.
    """
    from app import llm

    datos = [{k: i[k] for k in ("type", "title", "why", "urgency", "link", "when", "detail") if i.get(k) is not None} for i in items[:25]]
    clave = hashlib.sha256(f"{actor}|{json.dumps(datos, sort_keys=True)}".encode()).hexdigest()
    previo = _CACHE.get(clave)
    if previo and time.monotonic() - previo["t"] < CACHE_SEGUNDOS:
        return {**previo["r"], "cached": True}
    cobrar()
    r = llm.generar("inicio.prioridades", SISTEMA.format(org=config.ORG_NAME),
                    guardas.delimitar({"pendientes": datos, "total": len(items)}), usuario=actor)
    salida = {"text": r.texto.strip(), "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "items": len(items), "trace_id": r.traza_id}
    if len(_CACHE) > 200:
        _CACHE.clear()
    _CACHE[clave] = {"t": time.monotonic(), "r": salida}
    return {**salida, "cached": False}


def _alerta_de(i: Incident) -> str:
    return str((i.alerts or [{}])[0].get("name") or i.title.split(" · ")[0])


def _cerrar_el_ciclo(s, actor: str, ahora: datetime, agregar) -> None:
    """Fase 7.1: diagnósticos sin marcar, alertas ruidosas sin silencio y acciones del post-mortem abiertas."""
    desde = ahora - CICLO
    terminados = list(s.scalars(select(Incident).where(
        Incident.status.in_(("resuelto", "cerrado")), Incident.parent_id.is_(None), Incident.resolved_at >= desde)
        .order_by(Incident.resolved_at.desc())))

    sin_marcar = [i for i in terminados if i.diagnosis_status == "listo" and not i.feedback
                  and i.closed_reason not in ("ruido", "falso_positivo", "duplicado") and (not i.assignee or _yo(i.assignee, actor))]
    porque = "¿Acertó el diagnóstico? Márcalo: los correctos alimentan la base de conocimiento del agente"
    if len(sin_marcar) <= MAX_SUELTOS:
        for i in sin_marcar:
            agregar("marcar", f"#{i.id} {i.title}", porque, 1, f"#/operacion/incidentes/{i.id}", i.resolved_at)
    else:
        i = sin_marcar[0]
        agregar("marcar", f"{len(sin_marcar)} incidentes resueltos sin marcar el diagnóstico", f"{porque}. Empieza por el #{i.id}",
                1, f"#/operacion/incidentes/{i.id}", i.resolved_at)

    vigentes = ajustes.silencios(ahora)
    ruido: Dict[tuple, List[Incident]] = {}
    for i in terminados:
        if i.closed_reason in ("ruido", "falso_positivo"):
            ruido.setdefault((i.cluster, _alerta_de(i)), []).append(i)
    for (cluster, alerta), lista in ruido.items():
        if len(lista) >= 2 and not ajustes.silenciado(vigentes, cluster, None, alerta, []):
            agregar("ruido", f"{alerta} en {cluster or 'sin clúster'}",
                    f"Cerrada como ruido {len(lista)} veces en 14 días: silénciala (Silenciar similares…) o ajusta la regla",
                    1, f"#/operacion/incidentes/{lista[0].id}", lista[0].resolved_at)

    for a, i in s.execute(select(IncidentAction, Incident).join(Incident, Incident.id == IncidentAction.incident_id)
                          .where(IncidentAction.done_at.is_(None))):
        if _yo(a.owner, actor) or (not a.owner and (not i.assignee or _yo(i.assignee, actor))):
            agregar("accion", a.text, f"Acción de seguimiento del incidente #{i.id}", 1, f"#/operacion/incidentes/{i.id}", a.created_at)


def cambios(desde: datetime) -> Dict[str, Any]:
    """Lo nuevo desde `desde`: incidentes, hallazgos (nuevos y resueltos), recursos (nuevos y borrados) y alertas de costo."""
    def contar(s, modelo, *condiciones):
        return s.scalar(select(func.count()).select_from(modelo).where(*condiciones)) or 0

    with db.session_scope() as s:
        nuevos = [{"id": i.id, "title": i.title, "severity": i.severity, "status": i.status} for i in s.scalars(
            select(Incident).where(Incident.opened_at >= desde, Incident.parent_id.is_(None)).order_by(Incident.opened_at.desc()).limit(5))]
        return {
            "since": desde.isoformat(timespec="seconds"),
            "incidents": {"new": contar(s, Incident, Incident.opened_at >= desde, Incident.parent_id.is_(None)),
                          "resolved": contar(s, Incident, Incident.resolved_at >= desde, Incident.parent_id.is_(None)), "latest": nuevos},
            "findings": {"new": contar(s, Finding, Finding.first_seen >= desde),
                         "new_critical": contar(s, Finding, Finding.first_seen >= desde, Finding.severity == "critica"),
                         "resolved": contar(s, Finding, Finding.resolved_at >= desde)},
            "resources": {"new": contar(s, Resource, Resource.first_seen >= desde),
                          "new_outside_iac": contar(s, Resource, Resource.first_seen >= desde,
                                                   or_(Resource.in_iac_state == false(), Resource.in_iac_state.is_(None))),
                          "deleted": contar(s, Resource, Resource.deleted_at >= desde)},
            "cost_alerts": {"new": contar(s, CostEvent, CostEvent.opened_at >= desde)},
        }

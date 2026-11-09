"""
Dominio Inicio (fase 5 del plan 10): *Mis pendientes* y *Qué cambió*.

- **Mis pendientes** lee el contrato común de gestión (estado y responsable) de incidentes, hallazgos y
  alertas de costo, más lo que vence pronto (riesgos aceptados, excepciones de control, silencios). Cada
  pendiente trae el porqué y una urgencia de 0 a 3 para ordenarlos.
- **Qué cambió** cuenta lo nuevo desde un momento (la última visita, que recuerda el panel).
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import false, func, or_, select

from app.ai.incidentes import ABIERTOS
from app.core import ajustes
from app.db import engine as db
from app.db.models import ControlException, CostEvent, Finding, Incident, Resource, Rule

URGENCIA = {"critica": 3, "alta": 2, "media": 1}
PRONTO = timedelta(days=14)


def _yo(valor: Optional[str], actor: str) -> bool:
    return bool(valor) and valor.strip().lower() == actor.strip().lower()


def pendientes(actor: str, ahora: Optional[datetime] = None) -> List[Dict[str, Any]]:
    ahora = ahora or datetime.now(timezone.utc)
    hoy, items = ahora.date(), []

    def agregar(tipo, titulo, porque, urgencia, enlace, cuando=None):
        items.append({"type": tipo, "title": titulo, "why": porque, "urgency": urgencia, "link": enlace,
                      "when": cuando.isoformat() if cuando else None})

    with db.session_scope() as s:
        for i in s.scalars(select(Incident).where(Incident.status.in_(ABIERTOS), Incident.parent_id.is_(None))):
            if _yo(i.assignee, actor):
                agregar("incidente", f"#{i.id} {i.title}", f"Asignado a ti · {i.status.replace('_', ' ')}", URGENCIA.get(i.severity, 1),
                        f"#/operacion/incidentes/{i.id}", i.opened_at)
            elif not i.assignee and i.severity in ("critica", "alta"):
                agregar("incidente", f"#{i.id} {i.title}", f"Severidad {i.severity} y sin responsable", URGENCIA[i.severity],
                        f"#/operacion/incidentes/{i.id}", i.opened_at)

        filas = s.execute(select(Finding, Rule.title, Resource.name).join(Rule, Rule.id == Finding.rule_id)
                          .outerjoin(Resource, Resource.uid == Finding.resource_uid)
                          .where(Finding.status != "resuelto"))
        for f, regla, recurso in filas:
            titulo = f"{regla} · {recurso or f.resource_uid.rsplit('/', 1)[-1]}"
            if f.status == "aceptado" and f.accepted_until and f.accepted_until - hoy <= PRONTO:
                vence = (f.accepted_until - hoy).days
                agregar("hallazgo", titulo, "Riesgo aceptado vencido" if vence < 0 else f"Riesgo aceptado: vence en {vence} día(s)",
                        2 if vence <= 3 else 1, "#/riesgo/hallazgos")
            elif f.status in ("abierto", "asumido") and _yo(f.owner, actor):
                atrasado = f.due_date is not None and f.due_date < hoy
                agregar("hallazgo", titulo, f"Asignado a ti · vencido el {f.due_date.isoformat()}" if atrasado else
                        f"Asignado a ti{f' · vence el {f.due_date.isoformat()}' if f.due_date else ''}",
                        min(3, URGENCIA.get(f.severity, 1) + atrasado), "#/riesgo/hallazgos")

        for e in s.scalars(select(CostEvent).where(CostEvent.status.in_(("abierto", "reconocido")))):
            if _yo(e.assignee, actor) or not e.assignee:
                agregar("costo", e.title, "Asignada a ti" if e.assignee else "Alerta de costo sin responsable",
                        2 if e.kind == "presupuesto" else 1, "#/costos/alertas", e.opened_at)

        for x in s.scalars(select(ControlException).where(ControlException.revoked_at.is_(None))):
            if x.until - hoy <= PRONTO and x.until >= hoy:
                agregar("excepcion", f"Excepción {x.framework} {x.control}", f"Vence en {(x.until - hoy).days} día(s): renovar o corregir",
                        1, "#/riesgo/cumplimiento")

    for sil in ajustes.silencios(ahora):
        hasta = datetime.fromisoformat(sil["hasta"])
        if _yo(sil.get("creado_por"), actor) and hasta - ahora <= timedelta(hours=24):
            alcance = " · ".join(str(sil[k]) for k in ("cluster", "namespace", "alerta", "objeto") if sil.get(k))
            agregar("silencio", f"Silencio {alcance}", "Vence en menos de 24 h: lo que calla vuelve a avisar", 1, "#/operacion/silencios", hasta)

    return sorted(items, key=lambda x: (-x["urgency"], x["when"] or ""))


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

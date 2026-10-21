"""
Avisos al terminar el job (fase 3; eventos en docs/plan/02-arquitectura-objetivo.md#eventos-y-acciones).

Envia a un webhook (Teams Workflows o Slack, segun el host de `NOTIFY_WEBHOOK_URL`):

- `finding.opened`: hallazgos de severidad alta o critica detectados, reabiertos
  o con la aceptacion vencida desde el ultimo aviso.
- `collector.failed`: recolectores cuyas dos ultimas ejecuciones fallaron.

Deduplicacion: los eventos de hallazgo solo existen en las transiciones, asi que
un hallazgo que sigue abierto no se repite. La marca de agua es el `until` de la
ultima ejecucion `notify` correcta; si el envio falla, la ejecucion queda en
error y la siguiente reintenta desde la misma marca.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List
from urllib.parse import urlparse

import requests
from sqlalchemy import select

from app.collectors.common import Contexto, Resultado
from app.core import config
from app.db.models import CollectorRun, Finding, FindingEvent, Resource, Rule

SEVERIDADES = ("critica", "alta")
EVENTOS = ("detectado", "reabierto", "vencido")
# Sin aviso previo, solo lo de la ultima ventana del job: configurar el webhook
# no debe vaciar sobre el canal la historia completa.
PRIMERA_VENTANA = timedelta(hours=26)
MAX_EN_MENSAJE = 15


def _desde(session, momento: datetime) -> datetime:
    previa = session.scalars(
        select(CollectorRun).where(CollectorRun.collector == "notify", CollectorRun.status.in_(("ok", "parcial")))
        .order_by(CollectorRun.started_at.desc()).limit(1)).first()
    if previa and previa.detail.get("until"):
        return datetime.fromisoformat(previa.detail["until"])
    return momento - PRIMERA_VENTANA


def hallazgos_nuevos(session, desde: datetime, hasta: datetime) -> List[Dict]:
    filas = session.execute(
        select(FindingEvent.kind, Finding, Rule.title, Resource.name)
        .join(Finding, Finding.id == FindingEvent.finding_id)
        .join(Rule, Rule.id == Finding.rule_id)
        .outerjoin(Resource, Resource.uid == Finding.resource_uid)
        .where(FindingEvent.kind.in_(EVENTOS), FindingEvent.at > desde, FindingEvent.at <= hasta,
               Finding.severity.in_(SEVERIDADES), Finding.status == "abierto")
        .order_by(Finding.severity.desc(), FindingEvent.at)).all()
    vistos, salida = set(), []
    for tipo, f, titulo, nombre in filas:
        if f.id not in vistos:
            vistos.add(f.id)
            salida.append({"kind": tipo, "severity": f.severity, "title": titulo,
                           "resource": nombre or f.resource_uid.rsplit("/", 1)[-1], "account": f.account_uid})
    return salida


def recolectores_caidos(session, desde: datetime) -> List[str]:
    caidos = []
    nombres = session.scalars(select(CollectorRun.collector).where(CollectorRun.collector != "notify").distinct())
    for nombre in sorted(nombres):
        ultimas = session.scalars(select(CollectorRun).where(CollectorRun.collector == nombre)
                                  .order_by(CollectorRun.started_at.desc()).limit(2)).all()
        # Se repite cada dia mientras siga caido: es un recordatorio, no ruido.
        if len(ultimas) == 2 and all(r.status == "error" for r in ultimas) and _utc(ultimas[0].started_at) > desde:
            caidos.append(nombre)
    return caidos


def _utc(momento: datetime) -> datetime:
    # SQLite devuelve fechas sin zona; Azure SQL, con zona.
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def mensaje(hallazgos: List[Dict], caidos: List[str]) -> Dict[str, object]:
    lineas = []
    if hallazgos:
        lineas.append(f"**{len(hallazgos)} hallazgo(s) de severidad alta o crítica**")
        etiqueta = {"detectado": "nuevo", "reabierto": "reabierto", "vencido": "aceptación vencida"}
        lineas += [f"- [{h['severity']}] {h['title']}: {h['resource']} ({etiqueta[h['kind']]})"
                   for h in hallazgos[:MAX_EN_MENSAJE]]
        if len(hallazgos) > MAX_EN_MENSAJE:
            lineas.append(f"- … y {len(hallazgos) - MAX_EN_MENSAJE} más")
    if caidos:
        lineas.append(f"**Recolectores con dos fallas seguidas:** {', '.join(caidos)}")
    enlace = f"{config.FRONTEND_URL}/#/{'secops/gestion' if hallazgos else 'admin'}"
    return {"titulo": f"{config.APP_NAME}: requiere atención", "lineas": lineas, "enlace": enlace}


def payload(url: str, m: Dict[str, object]) -> Dict[str, object]:
    texto = "\n".join(m["lineas"])
    if (urlparse(url).hostname or "").endswith("hooks.slack.com"):
        return {"text": f"*{m['titulo']}*\n{texto.replace('**', '*')}\n<{m['enlace']}|Abrir en el panel>"}
    # Teams: webhook de Workflows con tarjeta adaptable (los conectores de Office 365 se retiraron).
    return {"type": "message", "attachments": [{
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": {
            "type": "AdaptiveCard", "version": "1.4", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "body": [{"type": "TextBlock", "text": m["titulo"], "weight": "Bolder", "size": "Medium", "wrap": True},
                     {"type": "TextBlock", "text": texto, "wrap": True}],
            "actions": [{"type": "Action.OpenUrl", "title": "Abrir en el panel", "url": m["enlace"]}],
        }}]}


def recolectar(ctx: Contexto, session) -> Resultado:
    hasta = ctx.momento
    desde = _desde(session, hasta)
    hallazgos = hallazgos_nuevos(session, desde, hasta)
    caidos = recolectores_caidos(session, desde)
    detalle = {"since": desde.isoformat(), "until": hasta.isoformat(), "findings": len(hallazgos), "collectors_failed": caidos}

    url = os.getenv("NOTIFY_WEBHOOK_URL", "").strip()
    if not (hallazgos or caidos):
        return Resultado(detail=detalle)
    if not url:
        return Resultado(status="parcial", detail={**detalle, "reason": "NOTIFY_WEBHOOK_URL sin configurar"})
    # La URL es una credencial: el error que queda en collector_runs solo lleva el host.
    # Sin `until` registrado (error), la siguiente ejecucion vuelve a avisar lo mismo.
    try:
        respuesta = requests.post(url, json=payload(url, mensaje(hallazgos, caidos)), timeout=30)
    except requests.RequestException as exc:
        raise RuntimeError(f"El webhook ({urlparse(url).hostname}) no respondio: {type(exc).__name__}") from None
    if respuesta.status_code >= 300:
        raise RuntimeError(f"El webhook ({urlparse(url).hostname}) respondio {respuesta.status_code}")
    return Resultado(items=len(hallazgos) + len(caidos), detail=detalle)

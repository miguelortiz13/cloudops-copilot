"""
Avisos al terminar el job (fase 3; eventos en docs/plan/02-arquitectura-objetivo.md#eventos-y-acciones).

Envia a un webhook (Discord, Slack o Teams Workflows, segun el host de `NOTIFY_WEBHOOK_URL`):

- `finding.opened`: hallazgos de severidad alta o critica detectados, reabiertos
  o con la aceptacion vencida desde el ultimo aviso.
- `collector.failed`: recolectores cuyas dos ultimas ejecuciones fallaron.
- `cost.anomaly`: dia de una cuenta con gasto > media de 14 dias + 3 desviaciones, o > 2x.
- `budget.threshold`: gasto del mes de una nube >= 80 % o 100 % de `MONTHLY_BUDGETS_USD`
  (`azure=5,aws=5`), o pronostico del mes >= 100 %.

Deduplicacion: los eventos de hallazgo solo existen en las transiciones, asi que
un hallazgo que sigue abierto no se repite. La marca de agua es el `until` de la
ultima ejecucion `notify` correcta; si el envio falla, la ejecucion queda en
error y la siguiente reintenta desde la misma marca. Los avisos de costo no son
transiciones: sus claves (cuenta y dia, nube y mes) quedan en `detail.sent` y no se
repiten mientras sigan vigentes.
"""

import calendar
import os
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests
from sqlalchemy import func, select

from app.collectors.common import Contexto, Resultado
from app.core import config
from app.db.models import Account, CollectorRun, CostDaily, Finding, FindingEvent, Resource, Rule

SEVERIDADES = ("critica", "alta")
EVENTOS = ("detectado", "reabierto", "vencido")
# Sin aviso previo, solo lo de la ultima ventana del job: configurar el webhook
# no debe vaciar sobre el canal la historia completa.
PRIMERA_VENTANA = timedelta(hours=26)
MAX_EN_MENSAJE = 15
VENTANA_BASE = 14
# Los costos llegan con hasta 72 h de retraso: se revisan los ultimos dias completos.
DIAS_A_REVISAR = 3
# Con presupuestos de pocos dolares, "el doble" de centavos es ruido.
MINIMO_ANOMALIA = 0.5
# Antes de esto el pronostico del mes extrapola dos o tres dias.
DIA_MINIMO_PRONOSTICO = 8


def _previa(session) -> Optional[CollectorRun]:
    return session.scalars(
        select(CollectorRun).where(CollectorRun.collector == "notify", CollectorRun.status.in_(("ok", "parcial")))
        .order_by(CollectorRun.started_at.desc()).limit(1)).first()


def _desde(previa: Optional[CollectorRun], momento: datetime) -> datetime:
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


def anomalias(session, hoy: date) -> List[Dict]:
    inicio = hoy - timedelta(days=VENTANA_BASE + DIAS_A_REVISAR)
    por_cuenta: Dict[str, Dict[date, float]] = {}
    for cuenta, dia, costo in session.execute(
            select(CostDaily.account_uid, CostDaily.charge_date, func.sum(CostDaily.billed_cost))
            .where(CostDaily.charge_date >= inicio, CostDaily.charge_date < hoy)
            .group_by(CostDaily.account_uid, CostDaily.charge_date)):
        por_cuenta.setdefault(cuenta, {})[dia] = float(costo or 0)
    nombres = dict(session.execute(select(Account.uid, Account.name)).all())
    salida = []
    for cuenta, dias in sorted(por_cuenta.items()):
        for atras in range(1, DIAS_A_REVISAR + 1):
            dia = hoy - timedelta(days=atras)
            costo = dias.get(dia, 0.0)
            # Un dia sin filas cuenta como 0: pasar de nada a gastar tambien es anomalia.
            base = [dias.get(dia - timedelta(days=i), 0.0) for i in range(1, VENTANA_BASE + 1)]
            media, desviacion = statistics.fmean(base), statistics.pstdev(base)
            if costo >= MINIMO_ANOMALIA and (costo > media + 3 * desviacion or costo > 2 * media):
                salida.append({"key": f"anomalia:{cuenta}:{dia}", "line":
                               f"- {nombres.get(cuenta, cuenta)}: {costo:.2f} USD el {dia:%d-%m} "
                               f"(media de {VENTANA_BASE} días: {media:.2f})"})
    return salida


def presupuestos(session, hoy: date) -> List[Dict]:
    limites = {nube.strip(): float(monto) for nube, monto in
               (p.split("=", 1) for p in os.getenv("MONTHLY_BUDGETS_USD", "").split(",") if p.strip())}
    if not limites:
        return []
    inicio = hoy.replace(day=1)
    gasto: Dict[str, float] = {}
    # shortcut: suma sin convertir moneda (hoy todo es USD); convertir si una cuenta factura en otra moneda.
    for cuenta, costo in session.execute(
            select(CostDaily.account_uid, func.sum(CostDaily.billed_cost))
            .where(CostDaily.charge_date >= inicio).group_by(CostDaily.account_uid)):
        nube = cuenta.split(":", 1)[0]
        gasto[nube] = gasto.get(nube, 0.0) + float(costo or 0)
    dias_mes = calendar.monthrange(hoy.year, hoy.month)[1]
    salida = []
    for nube, limite in limites.items():
        g = gasto.get(nube, 0.0)
        pronostico = g / max(hoy.day - 1, 1) * dias_mes
        nivel = "100" if g >= limite else "80" if g >= 0.8 * limite else None
        if not nivel and hoy.day >= DIA_MINIMO_PRONOSTICO and pronostico >= limite:
            nivel = "pronostico"
        if nivel:
            que = {"100": "superó", "80": "llegó al 80 % de", "pronostico": "va a superar"}[nivel]
            salida.append({"key": f"presupuesto:{nube}:{inicio:%Y-%m}:{nivel}", "line":
                           f"- {nube.upper()} {que} su presupuesto: {g:.2f} de {limite:.2f} USD en el mes "
                           f"(pronóstico {pronostico:.2f})"})
    return salida


def _utc(momento: datetime) -> datetime:
    # SQLite devuelve fechas sin zona; Azure SQL, con zona.
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def mensaje(hallazgos: List[Dict], caidos: List[str], costos: Optional[Dict[str, List[Dict]]] = None) -> Dict[str, object]:
    lineas = []
    costos = costos or {}
    if hallazgos:
        lineas.append(f"**{len(hallazgos)} hallazgo(s) de severidad alta o crítica**")
        etiqueta = {"detectado": "nuevo", "reabierto": "reabierto", "vencido": "aceptación vencida"}
        lineas += [f"- [{h['severity']}] {h['title']}: {h['resource']} ({etiqueta[h['kind']]})"
                   for h in hallazgos[:MAX_EN_MENSAJE]]
        if len(hallazgos) > MAX_EN_MENSAJE:
            lineas.append(f"- … y {len(hallazgos) - MAX_EN_MENSAJE} más")
    if caidos:
        lineas.append(f"**Recolectores con dos fallas seguidas:** {', '.join(caidos)}")
    if costos.get("presupuestos"):
        lineas += ["**Presupuesto**"] + [a["line"] for a in costos["presupuestos"]]
    if costos.get("anomalias"):
        lineas += ["**Gasto diario anómalo**"] + [a["line"] for a in costos["anomalias"][:MAX_EN_MENSAJE]]
    destino = "secops/gestion" if hallazgos else "admin" if caidos else "finops/historial"
    enlace = f"{config.FRONTEND_URL}/#/{destino}"
    return {"titulo": f"{config.APP_NAME}: requiere atención", "lineas": lineas, "enlace": enlace}


def payload(url: str, m: Dict[str, object]) -> Dict[str, object]:
    texto = "\n".join(m["lineas"])
    host = urlparse(url).hostname or ""
    if host in ("discord.com", "discordapp.com"):
        # Discord ya entiende **negrita**; la descripción de un embed admite 4096 caracteres.
        return {"embeds": [{"title": m["titulo"], "description": texto[:4096], "url": m["enlace"], "color": 0xEF4444}]}
    if host.endswith("hooks.slack.com"):
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
    previa = _previa(session)
    desde = _desde(previa, hasta)
    hallazgos = hallazgos_nuevos(session, desde, hasta)
    caidos = recolectores_caidos(session, desde)
    vigentes = {"presupuestos": presupuestos(session, hasta.date()), "anomalias": anomalias(session, hasta.date())}
    enviadas = set(previa.detail.get("sent", [])) if previa else set()
    costos = {tipo: [a for a in avisos if a["key"] not in enviadas] for tipo, avisos in vigentes.items()}
    detalle = {"since": desde.isoformat(), "until": hasta.isoformat(), "findings": len(hallazgos), "collectors_failed": caidos,
               "cost_alerts": sum(map(len, costos.values())),
               # Solo las vigentes: una clave que deja de serlo ya no puede repetirse y sale sola.
               "sent": sorted(a["key"] for avisos in vigentes.values() for a in avisos)}

    url = os.getenv("NOTIFY_WEBHOOK_URL", "").strip()
    if not (hallazgos or caidos or detalle["cost_alerts"]):
        return Resultado(detail=detalle)
    if not url:
        # Sin enviar nada, tampoco se marca nada como enviado.
        detalle["sent"] = sorted(enviadas)
        return Resultado(status="parcial", detail={**detalle, "reason": "NOTIFY_WEBHOOK_URL sin configurar"})
    # La URL es una credencial: el error que queda en collector_runs solo lleva el host.
    # Sin `until` registrado (error), la siguiente ejecucion vuelve a avisar lo mismo.
    try:
        respuesta = requests.post(url, json=payload(url, mensaje(hallazgos, caidos, costos)), timeout=30)
    except requests.RequestException as exc:
        raise RuntimeError(f"El webhook ({urlparse(url).hostname}) no respondio: {type(exc).__name__}") from None
    if respuesta.status_code >= 300:
        raise RuntimeError(f"El webhook ({urlparse(url).hostname}) respondio {respuesta.status_code}")
    return Resultado(items=len(hallazgos) + len(caidos) + detalle["cost_alerts"], detail=detalle)

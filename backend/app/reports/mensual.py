"""
Reporte ejecutivo mensual (fase 3): costos contra presupuesto, hallazgos,
inventario y salud del job de un mes, en PDF.

Lo arma el API a pedido (`/api/reports/monthly`) y el paso `report` del job lo
envia solo al webhook de avisos al empezar el mes siguiente.
"""

import calendar
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict

from sqlalchemy import func, select

from app.collectors.notify import limites_de_presupuesto
from app.core import config
from app.db.models import Account, CollectorRun, CostDaily, Finding, FindingEvent, Resource, Rule
from app.reports.pdf import GRIS, Pdf

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre")
SEVERIDADES = ("critica", "alta", "media", "baja")
TOP = 5
MAX_HALLAZGOS = 10


def nombre_del_mes(mes: date) -> str:
    return f"{MESES[mes.month - 1].capitalize()} {mes.year}"


def mes_anterior(d: date) -> date:
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


def datos(session, mes: date) -> Dict:
    """Cifras del mes que empieza en `mes`. Hallazgos abiertos e inventario son los de hoy."""
    fin = mes.replace(day=calendar.monthrange(mes.year, mes.month)[1])
    desde = datetime.combine(mes, time(), timezone.utc)
    hasta = datetime.combine(fin + timedelta(days=1), time(), timezone.utc)
    nombres = dict(session.execute(select(Account.uid, Account.name)).all())

    def gasto(columna, a: date, b: date):
        return [(k, float(c or 0)) for k, c in session.execute(
            select(columna, func.sum(CostDaily.billed_cost)).where(CostDaily.charge_date.between(a, b))
            .group_by(columna).order_by(func.sum(CostDaily.billed_cost).desc()))]

    por_cuenta = gasto(CostDaily.account_uid, mes, fin)
    anterior = sum(c for _, c in gasto(CostDaily.account_uid, mes_anterior(mes), mes - timedelta(days=1)))
    # shortcut: suma sin convertir moneda (hoy todo es USD); convertir si una cuenta factura en otra moneda.
    por_nube: Dict[str, float] = {}
    for cuenta, c in por_cuenta:
        por_nube[cuenta.split(":", 1)[0]] = por_nube.get(cuenta.split(":", 1)[0], 0.0) + c
    limites = limites_de_presupuesto()

    abiertos = dict(session.execute(select(Finding.severity, func.count()).where(Finding.status != "resuelto")
                                    .group_by(Finding.severity)).all())
    eventos = dict(session.execute(select(FindingEvent.kind, func.count()).where(
        FindingEvent.at >= desde, FindingEvent.at < hasta).group_by(FindingEvent.kind)).all())
    graves = session.execute(
        select(Finding.severity, Rule.title, Resource.name, Finding.resource_uid, Finding.status)
        .join(Rule, Rule.id == Finding.rule_id).outerjoin(Resource, Resource.uid == Finding.resource_uid)
        .where(Finding.status != "resuelto", Finding.severity.in_(("critica", "alta")))
        .order_by(Finding.severity.desc(), Finding.first_seen).limit(MAX_HALLAZGOS)).all()

    activos = Resource.deleted_at.is_(None)
    recursos = dict(session.execute(select(Resource.provider, func.count()).where(activos).group_by(Resource.provider)).all())
    en_iac = session.scalar(select(func.count()).select_from(Resource).where(activos, Resource.in_iac_state.is_(True)))
    nuevos = session.scalar(select(func.count()).select_from(Resource).where(
        Resource.first_seen >= desde, Resource.first_seen < hasta))
    borrados = session.scalar(select(func.count()).select_from(Resource).where(
        Resource.deleted_at >= desde, Resource.deleted_at < hasta))

    corridas = dict(session.execute(select(CollectorRun.status, func.count()).where(
        CollectorRun.started_at >= desde, CollectorRun.started_at < hasta).group_by(CollectorRun.status)).all())
    primera = session.scalar(select(func.min(CollectorRun.started_at)))

    return {
        "mes": mes, "fin": fin,
        "datos_desde": primera.date() if primera and primera.date() > mes else None,
        "total": sum(por_nube.values()), "anterior": anterior,
        "nubes": [{"nube": n, "gasto": por_nube.get(n, 0.0), "limite": limites.get(n)}
                  for n in sorted(set(por_nube) | set(limites))],
        "cuentas": [(nombres.get(k, k), c) for k, c in por_cuenta[:TOP]],
        "servicios": [(k or "Sin servicio", c) for k, c in gasto(CostDaily.service_name, mes, fin)[:TOP]],
        "abiertos": {s: abiertos.get(s, 0) for s in SEVERIDADES},
        "detectados": eventos.get("detectado", 0) + eventos.get("reabierto", 0),
        "resueltos": eventos.get("resuelto", 0),
        "graves": [{"severidad": sev, "regla": regla, "recurso": nombre or uid.rsplit("/", 1)[-1], "estado": estado}
                   for sev, regla, nombre, uid, estado in graves],
        "recursos": recursos, "en_iac": en_iac or 0, "nuevos": nuevos or 0, "borrados": borrados or 0,
        "corridas": corridas,
    }


def _usd(v: float) -> str:
    return f"{v:,.2f} USD"


def _corto(texto: str, n: int) -> str:
    return texto if len(texto) <= n else texto[:n - 1] + "…"


def pdf(d: Dict, generado: date) -> bytes:
    p = Pdf()
    p.fila([(0, f"{config.APP_NAME} · Reporte ejecutivo")], tam=18, negrita=True)
    p.fila([(0, f"{nombre_del_mes(d['mes'])} ({d['mes']:%d-%m} al {d['fin']:%d-%m-%Y}) · generado el {generado:%d-%m-%Y}")],
           color=GRIS)
    if d["datos_desde"]:
        p.fila([(0, f"La plataforma recolecta desde el {d['datos_desde']:%d-%m-%Y}: el mes no está completo.")], color=GRIS)

    def seccion(titulo: str):
        p.espacio(10)
        p.fila([(0, titulo)], tam=13, negrita=True)
        p.regla()

    seccion("Costos")
    # Sin gasto el mes anterior es casi siempre que la base no lo cubre: no se compara contra cero.
    anterior = (f"{_usd(d['anterior'])} ({(d['total'] - d['anterior']) / d['anterior'] * 100:+.0f} %)"
                if d["anterior"] else "sin datos")
    p.fila([(0, "Gasto del mes"), (160, _usd(d["total"])), (280, f"Mes anterior: {anterior}")], negrita=True)
    p.fila([(0, "Nube"), (160, "Gasto"), (260, "Presupuesto"), (360, "Uso")], tam=9, color=GRIS)
    for n in d["nubes"]:
        limite = n["limite"]
        uso = n["gasto"] / limite if limite else None
        p.fila([(0, n["nube"].upper()), (160, _usd(n["gasto"])), (260, _usd(limite) if limite else "—"),
                (360, f"{uso * 100:.0f} %" if uso is not None else "—")])
        if uso is not None:
            p.barra(400, 95, uso, (0.86, 0.15, 0.15) if uso >= 1 else (0.95, 0.6, 0.1) if uso >= 0.8 else (0.13, 0.55, 0.3))
    for titulo, filas in (("Cuentas con más gasto", d["cuentas"]), ("Servicios con más gasto", d["servicios"])):
        if filas:
            p.fila([(0, titulo)], tam=9, color=GRIS)
            for nombre, costo in filas:
                p.fila([(10, _corto(nombre, 45)), (300, _usd(costo))])

    seccion("Seguridad")
    a = d["abiertos"]
    p.fila([(0, f"Hallazgos abiertos hoy: {sum(a.values())}"),
            (200, f"Crítica {a['critica']} · Alta {a['alta']} · Media {a['media']} · Baja {a['baja']}")], negrita=True)
    p.fila([(0, f"En el mes: {d['detectados']} detectados o reabiertos, {d['resueltos']} resueltos")])
    if d["graves"]:
        p.fila([(0, "Severidad"), (60, "Regla"), (320, "Recurso"), (450, "Estado")], tam=9, color=GRIS)
        for h in d["graves"]:
            p.fila([(0, h["severidad"]), (60, _corto(h["regla"], 48)), (320, _corto(h["recurso"], 24)), (450, h["estado"])],
                   tam=9)

    seccion("Inventario")
    total = sum(d["recursos"].values())
    por_nube = " · ".join(f"{k.upper()} {v}" for k, v in sorted(d["recursos"].items()))
    p.fila([(0, f"Recursos activos hoy: {total}"), (200, por_nube)], negrita=True)
    cobertura = f" ({d['en_iac'] / total * 100:.0f} %)" if total else ""
    p.fila([(0, f"En Terraform: {d['en_iac']}{cobertura} · nuevos en el mes: {d['nuevos']} · eliminados: {d['borrados']}")])

    seccion("Operación")
    c = d["corridas"]
    p.fila([(0, f"Ejecuciones de recolectores en el mes: {sum(c.values())}"),
            (260, f"correctas {c.get('ok', 0)} · parciales {c.get('parcial', 0)} · con error {c.get('error', 0)}")])

    p.espacio(16)
    p.fila([(0, f"Detalle en {config.FRONTEND_URL}")], tam=8, color=GRIS)
    return p.bytes()

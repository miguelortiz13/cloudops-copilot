"""
Envio del reporte ejecutivo del mes anterior (app/reports/mensual.py) al webhook
de avisos, una vez por mes.

Discord recibe el PDF adjunto; Slack y Teams Workflows no aceptan archivos por
webhook y reciben el resumen con el enlace a Reportes, donde se descarga.
El mes enviado queda en `detail.sent` y pasa de una ejecucion a la siguiente.
"""

import json
import os
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy import func, select

from app.collectors import notify
from app.collectors.common import Contexto, Resultado
from app.core import config
from app.db.models import CollectorRun
from app.reports import mensual

# Los costos llegan con hasta 72 h de retraso: antes del dia 4 el mes anterior no esta cerrado.
DIA_DE_ENVIO = 4


def _enviado(session) -> Optional[str]:
    previa = session.scalars(select(CollectorRun).where(CollectorRun.collector == "report", CollectorRun.status == "ok")
                             .order_by(CollectorRun.started_at.desc()).limit(1)).first()
    return previa.detail.get("sent") if previa else None


def resumen(d) -> dict:
    nubes = ", ".join(f"{n['nube'].upper()} {n['gasto']:.2f}" + (f" de {n['limite']:.2f}" if n["limite"] else "")
                      for n in d["nubes"])
    a = d["abiertos"]
    return {"titulo": f"{config.APP_NAME}: reporte de {mensual.nombre_del_mes(d['mes']).lower()}",
            "lineas": [f"**Gasto:** {d['total']:.2f} USD ({nubes})",
                       f"**Hallazgos abiertos:** {sum(a.values())} (críticos {a['critica']}, altos {a['alta']}); "
                       f"{d['resueltos']} resueltos en el mes",
                       f"**Recursos:** {sum(d['recursos'].values())}, {d['en_iac']} en Terraform"],
            "enlace": f"{config.FRONTEND_URL}/#/reportes"}


def recolectar(ctx: Contexto, session) -> Resultado:
    hoy = ctx.momento.date()
    mes = mensual.mes_anterior(hoy)
    clave, enviado = f"{mes:%Y-%m}", _enviado(session)
    if enviado == clave or hoy.day < DIA_DE_ENVIO:
        return Resultado(detail={"sent": enviado})
    # Un mes anterior a la primera ejecucion no tiene nada que reportar.
    if session.scalar(select(func.min(CollectorRun.started_at))).date() >= hoy.replace(day=1):
        return Resultado(detail={"sent": enviado, "reason": f"Sin datos de {clave}"})
    url = os.getenv("NOTIFY_WEBHOOK_URL", "").strip()
    if not url:
        return Resultado(status="parcial", detail={"sent": enviado, "reason": "NOTIFY_WEBHOOK_URL sin configurar"})

    d = mensual.datos(session, mes)
    m = resumen(d)
    cuerpo = notify.payload(url, m, color=0x3B82F6)
    if (urlparse(url).hostname or "") in ("discord.com", "discordapp.com"):
        archivo = mensual.pdf(d, hoy)
        notify.enviar(url, data={"payload_json": json.dumps(cuerpo)},
                      files={"files[0]": (f"reporte-{clave}.pdf", archivo, "application/pdf")})
    else:
        notify.enviar(url, json=cuerpo)
    return Resultado(items=1, detail={"sent": clave})

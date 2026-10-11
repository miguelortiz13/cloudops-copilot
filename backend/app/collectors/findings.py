"""
Recolector de hallazgos y su ciclo de vida.

Estados: abierto -> asumido -> resuelto, o aceptado (riesgo aceptado hasta
`accepted_until`). En cada ejecucion:

- Detectado y no existia: se crea `abierto` (evento "detectado").
- Detectado y estaba `resuelto`: vuelve a `abierto` (evento "reabierto").
- Detectado, `aceptado` y la aceptacion vencio: vuelve a `abierto` ("vencido").
- No detectado y estaba abierto, asumido o aceptado: pasa a `resuelto`
  (evento "resuelto"). Solo si la consulta de su regla respondio: una consulta
  fallida no es evidencia de que el problema desaparecio.

Cada hallazgo es unico por (regla, recurso). El proveedor decide que es "el
recurso" (en Azure, la regla de seguridad concreta de un NSG) y que reglas no
pudo evaluar: el recolector no sabe de que nube vienen.
"""

from typing import Dict, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collectors.common import Contexto, Resultado
from app.compliance.catalog import POR_ID, REGLAS, frameworks_json
from app.db.models import Finding, FindingEvent, Rule
from app.providers.base import Hallazgo

ACTOR = "recolector"
ACTIVOS = ("abierto", "asumido", "aceptado")


def _sincronizar_reglas(session: Session) -> None:
    """El catalogo (app/compliance/catalog.py) es la fuente de verdad de `rules`."""
    existentes = {r.id: r for r in session.scalars(select(Rule))}
    for regla in REGLAS.values():
        campos = dict(capability=regla.capability, title=regla.title, severity_default=regla.severity_default,
                      remediation=regla.remediation, description=regla.description, detection=regla.detection,
                      frameworks=frameworks_json(regla), reference_urls=list(regla.references))
        fila = existentes.get(regla.id)
        if fila is None:
            session.add(Rule(id=regla.id, **campos))
        else:
            for campo, valor in campos.items():
                setattr(fila, campo, valor)
    session.flush()


def recolectar(ctx: Contexto, session: Session) -> Resultado:
    momento = ctx.momento
    hoy = momento.date()
    _sincronizar_reglas(session)

    resultado = ctx.proveedor.evaluar_reglas(ctx.cuentas_uid)
    reglas_sin_evidencia = set(resultado.reglas_sin_evidencia)

    detectados: Dict[Tuple[str, str], Hallazgo] = {}
    for h in resultado.hallazgos:
        if h.rule_id in POR_ID:
            detectados[(h.rule_id, h.resource_uid)] = h

    cuentas = ctx.cuentas_uid
    existentes: Dict[Tuple[str, str], Finding] = {
        (f.rule_id, f.resource_uid): f
        for f in session.scalars(select(Finding).where(Finding.account_uid.in_(cuentas)))
    }

    conteo = {"nuevos": 0, "reabiertos": 0, "vencidos": 0, "resueltos": 0}

    def evento(hallazgo: Finding, tipo: str, desde, hasta, nota=None):
        session.add(FindingEvent(finding_id=hallazgo.id, at=momento, kind=tipo, from_status=desde,
                                 to_status=hasta, actor=ACTOR, note=nota))

    for (regla_id, uid), item in detectados.items():
        detalle = dict(item.details)
        hallazgo = existentes.get((regla_id, uid))
        if hallazgo is None:
            hallazgo = Finding(rule_id=regla_id, resource_uid=uid, account_uid=item.account_uid,
                               severity=item.severity, status="abierto", details=detalle,
                               first_seen=momento, last_seen=momento)
            session.add(hallazgo)
            session.flush()
            evento(hallazgo, "detectado", None, "abierto")
            conteo["nuevos"] += 1
            continue

        hallazgo.last_seen = momento
        hallazgo.severity = item.severity or hallazgo.severity
        hallazgo.details = detalle
        if hallazgo.status == "resuelto":
            evento(hallazgo, "reabierto", "resuelto", "abierto")
            hallazgo.status, hallazgo.resolved_at = "abierto", None
            conteo["reabiertos"] += 1
        elif hallazgo.status == "aceptado" and hallazgo.accepted_until and hallazgo.accepted_until < hoy:
            evento(hallazgo, "vencido", "aceptado", "abierto",
                   f"La aceptación del riesgo venció el {hallazgo.accepted_until.isoformat()}.")
            hallazgo.status, hallazgo.accepted_until = "abierto", None
            conteo["vencidos"] += 1

    for clave, hallazgo in existentes.items():
        if clave in detectados or hallazgo.status not in ACTIVOS:
            continue
        if hallazgo.rule_id in reglas_sin_evidencia:
            continue
        evento(hallazgo, "resuelto", hallazgo.status, "resuelto", "Ya no se detecta.")
        hallazgo.status, hallazgo.resolved_at = "resuelto", momento
        conteo["resueltos"] += 1

    session.flush()
    abiertos = session.scalar(select(func.count()).select_from(Finding).where(
        Finding.account_uid.in_(cuentas), Finding.status.in_(("abierto", "asumido"))))
    return Resultado(
        items=len(detectados),
        status="parcial" if reglas_sin_evidencia else "ok",
        detail={**conteo, "rules_without_evidence": sorted(reglas_sin_evidencia), "open": abiertos},
    )

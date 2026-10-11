"""
Vistas de cumplimiento: estado por control, catalogo de reglas y activos
clasificados.

Estado de un control, de peor a mejor:

* `no_cumple`       — alguna regla que lo evidencia tiene hallazgos abiertos o
  asumidos (o, en los de clasificacion, hay activos sin clasificar o sin
  custodio).
* `sin_evidencia`   — alguna regla no se pudo evaluar en la ultima ejecucion
  (su consulta fallo) o el recolector todavia no corrio. No se presume que
  cumple.
* `riesgo_aceptado` — solo quedan hallazgos aceptados con vencimiento vigente.
* `cumple`          — todas sus reglas se evaluaron y no hay hallazgos activos.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.compliance import catalog
from app.compliance.classification import ambiente
from app.db.models import Account, AssetClassification, CollectorRun, Finding, Resource

ESTADOS = ("no_cumple", "sin_evidencia", "riesgo_aceptado", "cumple")
ACTIVOS = ("abierto", "asumido")


def _iso(momento: Optional[datetime]) -> Optional[str]:
    """ISO 8601 en UTC. SQLite devuelve las fechas sin zona; Azure SQL (DATETIMEOFFSET) con ella."""
    if momento is None:
        return None
    return (momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)).isoformat()


def _ultima(s: Session, recolector: str) -> Optional[CollectorRun]:
    return s.scalars(select(CollectorRun).where(
        CollectorRun.collector == recolector, CollectorRun.status.in_(("ok", "parcial")))
        .order_by(CollectorRun.finished_at.desc()).limit(1)).first()


def _reglas_sin_evidencia(corrida: Optional[CollectorRun]) -> Set[str]:
    if corrida is None:
        return {r.id for r in catalog.REGLAS.values()}
    detalle = corrida.detail or {}
    if "rules_without_evidence" in detalle:
        return set(detalle["rules_without_evidence"])
    # Ejecuciones anteriores a la capa de proveedores guardaban las consultas de Azure.
    fallidas = set(detalle.get("failed_queries") or [])
    return {catalog.REGLAS[t].id for t, consulta in catalog.CONSULTA_DE_TIPO.items() if consulta in fallidas}


def _peor(estados: List[str]) -> str:
    return min(estados, key=ESTADOS.index) if estados else "sin_evidencia"


def _conteo_por_regla(s: Session) -> Dict[str, Dict[str, Any]]:
    conteo: Dict[str, Dict[str, Any]] = {}
    for regla, estado, severidad, n in s.execute(
            select(Finding.rule_id, Finding.status, Finding.severity, func.count())
            .group_by(Finding.rule_id, Finding.status, Finding.severity)).all():
        c = conteo.setdefault(regla, {"active": 0, "accepted": 0, "resolved": 0, "by_severity": {}})
        if estado in ACTIVOS:
            c["active"] += n
            c["by_severity"][severidad] = c["by_severity"].get(severidad, 0) + n
        elif estado == "aceptado":
            c["accepted"] += n
        elif estado == "resuelto":
            c["resolved"] += n
    return conteo


def _evidencia_de_clasificacion(s: Session) -> Dict[str, Dict[str, Any]]:
    """Estado de A.5.9 (inventario con custodio) y A.5.12 (clasificacion)."""
    corrida = _ultima(s, "classification")
    total = s.scalar(select(func.count()).select_from(Resource).where(Resource.deleted_at.is_(None))) or 0
    clasificados = s.scalar(select(func.count()).select_from(AssetClassification).join(
        Resource, Resource.uid == AssetClassification.resource_uid).where(Resource.deleted_at.is_(None))) or 0
    sin_custodio = s.scalar(select(func.count()).select_from(AssetClassification).join(
        Resource, Resource.uid == AssetClassification.resource_uid).where(
        Resource.deleted_at.is_(None), AssetClassification.custodian.is_(None))) or 0
    sin_clasificar = total - clasificados

    def estado(fallas: int) -> str:
        if corrida is None or total == 0:
            return "sin_evidencia"
        return "no_cumple" if fallas else "cumple"

    return {
        "A.5.9": {"status": estado(sin_custodio + sin_clasificar), "match": "parcial",
                  "detail": f"{total - sin_custodio - sin_clasificar} de {total} activos inventariados con custodio",
                  "failing": sin_custodio + sin_clasificar},
        "A.5.12": {"status": estado(sin_clasificar), "match": "directa",
                   "detail": f"{clasificados} de {total} activos clasificados", "failing": sin_clasificar},
    }


def cumplimiento(s: Session) -> Dict[str, Any]:
    corrida = _ultima(s, "findings")
    sin_evidencia = _reglas_sin_evidencia(corrida)
    conteo = _conteo_por_regla(s)
    clasificacion = _evidencia_de_clasificacion(s)
    vacio = {"active": 0, "accepted": 0, "resolved": 0, "by_severity": {}}

    def estado_de_regla(regla_id: str) -> str:
        c = conteo.get(regla_id, vacio)
        if c["active"]:
            return "no_cumple"
        if regla_id in sin_evidencia:
            return "sin_evidencia"
        return "riesgo_aceptado" if c["accepted"] else "cumple"

    reglas = []
    for r in catalog.REGLAS.values():
        c = conteo.get(r.id, vacio)
        reglas.append({
            "id": r.id, "title": r.title, "severity_default": r.severity_default, "description": r.description,
            "detection": r.detection, "remediation": r.remediation, "references": list(r.references),
            "frameworks": catalog.frameworks_json(r), "status": estado_de_regla(r.id),
            "evaluated": r.id not in sin_evidencia, **c,
        })

    marcos = []
    for marco in catalog.MARCOS.values():
        controles = []
        for (m, cid), control in catalog.CONTROLES.items():
            if m != marco.id:
                continue
            evidencias, estados = [], []
            for r in catalog.REGLAS.values():
                for control_id, alcance in r.frameworks.get(m, ()):
                    if control_id != cid:
                        continue
                    c = conteo.get(r.id, vacio)
                    estados.append(estado_de_regla(r.id))
                    evidencias.append({"kind": "rule", "rule_id": r.id, "title": r.title, "match": alcance,
                                       "status": estados[-1], "active": c["active"], "accepted": c["accepted"]})
            if (m, cid) in catalog.CONTROLES_DE_CLASIFICACION:
                e = clasificacion[cid]
                estados.append(e["status"])
                evidencias.append({"kind": "classification", "title": e["detail"], "match": e["match"],
                                   "status": e["status"], "active": e["failing"], "accepted": 0})
            controles.append({
                "id": cid, "title": control.titulo, "status": _peor(estados), "evidence": evidencias,
                "direct": any(e["match"] == "directa" for e in evidencias),
                "active": sum(e["active"] for e in evidencias), "accepted": sum(e["accepted"] for e in evidencias),
            })
        resumen = {e: sum(1 for c in controles if c["status"] == e) for e in ESTADOS}
        marcos.append({"id": marco.id, "name": marco.nombre, "version": marco.version, "url": marco.url,
                       "controls_evaluated": len(controles), "summary": resumen, "controls": controles})

    return {
        "available": True,
        "frameworks": marcos,
        "rules": reglas,
        "evaluated_at": _iso(corrida.finished_at) if corrida else None,
        "failed_rules": sorted(sin_evidencia) if corrida else [],
    }


def activos(s: Session) -> Dict[str, Any]:
    cuentas = dict(s.execute(select(Account.uid, Account.name)).all())
    filas = s.execute(select(Resource, AssetClassification).outerjoin(
        AssetClassification, AssetClassification.resource_uid == Resource.uid).where(Resource.deleted_at.is_(None))).all()
    activos_por_recurso: Dict[str, int] = {}
    for uid, n in s.execute(select(Finding.resource_uid, func.count()).where(
            Finding.status.in_(ACTIVOS)).group_by(Finding.resource_uid)).all():
        # Un hallazgo de NSG apunta a la regla de seguridad: cuenta para el NSG.
        base = uid.split("/securityrules/")[0]
        activos_por_recurso[base] = activos_por_recurso.get(base, 0) + n

    items = []
    for r, c in filas:
        items.append({
            "uid": r.uid, "name": r.name, "type": r.native_type, "group": r.group_name,
            "account": cuentas.get(r.account_uid), "environment": ambiente(r.tags) or None,
            "classification": c.classification if c else None,
            "confidentiality": c.confidentiality if c else None, "integrity": c.integrity if c else None,
            "availability": c.availability if c else None,
            "score": (c.confidentiality + c.integrity + c.availability) if c else None,
            "risk_required": c.risk_required if c else None, "custodian": c.custodian if c else None,
            "method": c.method if c else None, "reason": c.reason if c else None,
            "updated_by": c.updated_by if c else None,
            "updated_at": _iso(c.updated_at) if c else None,
            "open_findings": activos_por_recurso.get(r.uid, 0),
        })
    orden = {"Confidencial": 0, "Restringido": 1, "Uso interno": 2}
    items.sort(key=lambda a: (orden.get(a["classification"], 3), -(a["score"] or 0), a["name"].lower()))

    clasificados = [a for a in items if a["classification"]]
    por_clase: Dict[str, int] = {}
    for a in clasificados:
        por_clase[a["classification"]] = por_clase.get(a["classification"], 0) + 1
    corrida = _ultima(s, "classification")
    return {
        "available": True,
        "items": items,
        "stats": {
            "total": len(items),
            "classified": len(clasificados),
            "by_class": por_clase,
            "risk_required": sum(1 for a in clasificados if a["risk_required"]),
            "manual": sum(1 for a in clasificados if a["method"] == "manual"),
            "without_custodian": sum(1 for a in items if not a["custodian"]),
            "average_score": round(sum(a["score"] for a in clasificados) / len(clasificados), 2) if clasificados else 0,
        },
        "collected_at": _iso(corrida.finished_at) if corrida else None,
    }

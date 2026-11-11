"""
Tablero de valor (fase 7.2, plan 12): si la plataforma mejora la operación, con números de producción.

Por semana ISO (lunes a domingo, UTC), de los incidentes abiertos esa semana: tiempo hasta reconocer (primera
acción de una persona: estado, responsable, nota o acción), tiempo hasta resolver, % de ruido, cobertura de
marcas del diagnóstico y % de correctos; de los hallazgos críticos y altos: detectados, resueltos y días para
cerrar. Más el ahorro realizado y la última corrida de evals.
"""

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select

from app.core import config
from app.db import engine as db
from app.db.models import Finding, FindingEvent, Incident, IncidentEvent

HUMANAS = ("estado", "asignado", "nota", "accion")
GRAVES = ("critica", "alta")


def _mediana(valores: List[float]) -> Optional[float]:
    valores = sorted(valores)
    return round(valores[len(valores) // 2], 1) if valores else None


def _pct(parte: int, total: int) -> Optional[float]:
    return round(parte / total * 100, 1) if total else None


def _min(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 60


def _utc(d: Optional[datetime]) -> Optional[datetime]:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def semanas(n: int, ahora: datetime) -> List[datetime]:
    """Inicio (lunes 00:00 UTC) de las últimas `n` semanas, la actual al final."""
    lunes = datetime.combine(ahora.date() - timedelta(days=ahora.weekday()), time(), timezone.utc)
    return [lunes - timedelta(weeks=k) for k in range(n - 1, -1, -1)]


def _incidentes(lista: List[Incident], humanas: Dict[int, datetime]) -> Dict[str, Any]:
    terminados = [i for i in lista if i.resolved_at]
    diagnosticados = [i for i in terminados if i.diagnosis_status == "listo" and i.closed_reason not in ("ruido", "falso_positivo", "duplicado")]
    marcados = [i for i in diagnosticados if i.feedback]
    return {
        "total": len(lista),
        "mtta_min": _mediana([_min(_utc(i.opened_at), humanas[i.id]) for i in lista if i.id in humanas]),
        "mttr_min": _mediana([_min(_utc(i.opened_at), _utc(i.resolved_at)) for i in terminados]),
        "noise_pct": _pct(sum(1 for i in terminados if i.closed_reason in ("ruido", "falso_positivo")), len(terminados)),
        "marked_pct": _pct(len(marcados), len(diagnosticados)),
        "correct_pct": _pct(sum(1 for i in marcados if i.feedback == "correcto"), len(marcados)),
    }


def tablero(n: int = 8, ahora: Optional[datetime] = None) -> Dict[str, Any]:
    ahora = ahora or datetime.now(timezone.utc)
    inicios = semanas(n, ahora)
    desde = inicios[0]
    with db.session_scope() as s:
        incidentes = list(s.scalars(select(Incident).where(Incident.opened_at >= desde, Incident.parent_id.is_(None))))
        humanas: Dict[int, datetime] = {}
        if incidentes:
            for e in s.scalars(select(IncidentEvent).where(IncidentEvent.incident_id.in_([i.id for i in incidentes]),
                                                           IncidentEvent.kind.in_(HUMANAS)).order_by(IncidentEvent.at)):
                humanas.setdefault(e.incident_id, _utc(e.at))
        eventos = list(s.execute(select(FindingEvent.kind, FindingEvent.at).join(Finding, Finding.id == FindingEvent.finding_id)
                                 .where(FindingEvent.at >= desde, Finding.severity.in_(GRAVES))))
        cerrados = list(s.execute(select(Finding.first_seen, Finding.resolved_at).where(
            Finding.resolved_at >= desde, Finding.severity.in_(GRAVES))))
        abiertos = s.scalar(select(func.count()).select_from(Finding).where(Finding.status != "resuelto", Finding.severity.in_(GRAVES)))

    salida = []
    for k, ini in enumerate(inicios):
        fin = inicios[k + 1] if k + 1 < len(inicios) else ahora + timedelta(seconds=1)
        dentro = lambda d: d is not None and ini <= _utc(d) < fin  # noqa: E731
        salida.append({
            "week": f"{ini.isocalendar().year}-W{ini.isocalendar().week:02d}", "start": ini.date().isoformat(),
            "incidents": _incidentes([i for i in incidentes if dentro(i.opened_at)], humanas),
            "findings": {"detected": sum(1 for kind, at in eventos if kind in ("detectado", "reabierto") and dentro(at)),
                         "resolved": sum(1 for kind, at in eventos if kind == "resuelto" and dentro(at)),
                         "days_to_close": _mediana([(_utc(r) - _utc(f)).total_seconds() / 86400 for f, r in cerrados if dentro(r)])},
        })

    from app.dominios.costos import ahorro

    return {"weeks": salida, "findings_open": abiertos, "savings": ahorro.realizado(90, ahora)["totals"], "evals": _ultimos_evals()}


def _ultimos_evals() -> Optional[Dict[str, Any]]:
    try:
        lineas = (config.DATA_DIR / "evals" / "historial.jsonl").read_text(encoding="utf-8").strip().splitlines()
    except FileNotFoundError:
        return None
    if not lineas:
        return None
    ultima = json.loads(lineas[-1])
    suites = [{k: x.get(k) for k in ("suite", "accuracy", "target")} for x in ultima.get("suites", [])]
    return {"at": ultima.get("at"), "suites": suites,
            "on_target": sum(1 for x in suites if (x["accuracy"] or 0) >= (x["target"] or 0))}


def tendencia(ahora: Optional[datetime] = None) -> Dict[str, Any]:
    """La semana cerrada y la anterior, para el resumen semanal y el reporte (citan la tendencia)."""
    ahora = ahora or datetime.now(timezone.utc)
    semanas_ = tablero(3, ahora)["weeks"][:2]  # las dos semanas cerradas antes de la actual
    return {"semana_anterior": semanas_[0], "ultima_semana": semanas_[1]}


def _prueba() -> None:
    lunes = semanas(2, datetime(2026, 11, 12, 15, tzinfo=timezone.utc))
    assert [d.date() for d in lunes] == [date(2026, 11, 2), date(2026, 11, 9)]
    assert _mediana([30, 10, 20]) == 20 and _mediana([]) is None and _pct(1, 4) == 25.0 and _pct(0, 0) is None


_prueba()

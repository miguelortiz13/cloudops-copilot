"""
SLOs con presupuesto de error (fase 7.3, plan 12) sobre los chequeos HTTP.

Cada chequeo deja su resultado en `DATA_DIR/chequeos/AAAA-MM.jsonl`. El SLI de una URL es la proporción de
chequeos correctos en la ventana (por defecto 28 días) contra su objetivo (por defecto 99,5 %, en
Plataforma → Ajustes → Chequeos). El presupuesto de error es la falla permitida, `1 - objetivo`.

*Burn rate* = tasa de error en una ventana / presupuesto: 1 gasta el presupuesto justo en la ventana del SLO.
Se alerta con dos ventanas (como el SRE workbook): 1 hora a 14,4× **y** 6 horas a 6×, que en 28 días son el
2 % y el 5 % del presupuesto. Con un chequeo cada 10 minutos, eso es por ejemplo 2 fallas en la última hora
con 99,5 %. La alerta se resuelve cuando la quema de la última hora vuelve por debajo de 1.

Para no duplicar ni alertar con poca historia: hacen falta al menos 3 horas de muestras en la ventana de
6 horas, y no se alerta mientras el chequeo de esa URL ya tiene su incidente abierto (está caída). Así el SLO
cubre lo que el chequeo no ve: fallas intermitentes que nunca son dos seguidas.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core import ajustes, config

RAPIDA, LENTA = (timedelta(hours=1), 14.4), (timedelta(hours=6), 6.0)
MIN_MUESTRAS_LENTA = 18  # 3 horas de chequeos cada 10 minutos


def _carpeta() -> Path:
    return Path(config.DATA_DIR) / "chequeos"


def anotar(url: str, resultado: Dict[str, Any], ahora: datetime) -> None:
    """Una línea por chequeo: es la serie del SLI."""
    # shortcut: append sin bloqueo, como avisos y trazas (k8s-watch es el único que escribe); a una tabla si crece.
    carpeta = _carpeta()
    carpeta.mkdir(parents=True, exist_ok=True)
    with open(carpeta / f"{ahora:%Y-%m}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": ahora.isoformat(timespec="seconds"), "url": url, "ok": bool(resultado["ok"]),
                            "ms": resultado.get("ms")}) + "\n")


def leer(desde: datetime, ahora: datetime) -> List[Dict[str, Any]]:
    filas: List[Dict[str, Any]] = []
    mes = desde.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while mes <= ahora:
        try:
            with open(_carpeta() / f"{mes:%Y-%m}.jsonl", encoding="utf-8") as f:
                filas += [json.loads(linea) for linea in f if linea.strip()]
        except FileNotFoundError:
            pass
        mes = (mes + timedelta(days=32)).replace(day=1)
    corte = desde.isoformat()
    return [f for f in filas if f["at"] >= corte]


def _quema(filas: List[Dict[str, Any]], desde: datetime, presupuesto: float) -> Optional[float]:
    ventana = [f for f in filas if f["at"] >= desde.isoformat()]
    if not ventana or presupuesto <= 0:
        return None
    return round(sum(1 for f in ventana if not f["ok"]) / len(ventana) / presupuesto, 1)


def estado(ahora: Optional[datetime] = None, urls: Optional[List[str]] = None) -> Dict[str, Any]:
    """Cada URL con su disponibilidad en la ventana, el presupuesto restante y la quema en 1 h y 6 h."""
    ahora = ahora or datetime.now(timezone.utc)
    a = ajustes.seccion("chequeos")
    objetivo, dias = a["objetivo_pct"], a["ventana_dias"]
    presupuesto = 1 - objetivo / 100
    filas = leer(ahora - timedelta(days=dias), ahora)
    salida = []
    for url in (urls if urls is not None else a["urls"]):
        propias = [f for f in filas if f["url"] == url]
        fallas = sum(1 for f in propias if not f["ok"])
        disponibilidad = round((1 - fallas / len(propias)) * 100, 3) if propias else None
        consumido = round(fallas / len(propias) / presupuesto * 100, 1) if propias and presupuesto > 0 else None
        rapida, lenta = _quema(propias, ahora - RAPIDA[0], presupuesto), _quema(propias, ahora - LENTA[0], presupuesto)
        salida.append({
            "url": url, "samples": len(propias), "failures": fallas, "availability_pct": disponibilidad,
            "budget_consumed_pct": consumido, "budget_remaining_pct": None if consumido is None else round(100 - consumido, 1),
            "burn_1h": rapida, "burn_6h": lenta,
            "burning": bool(rapida is not None and lenta is not None and rapida >= RAPIDA[1] and lenta >= LENTA[1]
                            and sum(1 for f in propias if f["at"] >= (ahora - LENTA[0]).isoformat()) >= MIN_MUESTRAS_LENTA),
            "met": None if disponibilidad is None else disponibilidad >= objetivo,
        })
    return {"objective_pct": objetivo, "window_days": dias, "items": salida}


def alerta(url: str, s: Dict[str, Any], objetivo: float, dias: int, estado_: str, ahora: datetime) -> Dict[str, Any]:
    """Alerta con formato de Alertmanager, como los chequeos: entra como incidente con diagnóstico y avisos."""
    from urllib.parse import urlparse

    host = urlparse(url).hostname or url
    resumen = (f"{host} quema su presupuesto de error: {s['burn_1h']}x en 1 h y {s['burn_6h']}x en 6 h "
               f"(SLO {objetivo} % en {dias} días)")
    detalle = (f"Disponibilidad {s['availability_pct']} % en {dias} días, presupuesto restante {s['budget_remaining_pct']} %. "
               f"{s['failures']} chequeo(s) fallido(s) de {s['samples']}.")
    return {"version": "4", "status": estado_, "groupKey": f"slo:{url}",
            "alerts": [{"status": estado_, "startsAt": ahora.isoformat(), "endsAt": ahora.isoformat() if estado_ == "resolved" else "",
                        "labels": {"alertname": "SLOBurnRate", "instance": url[:200], "service": host, "severity": "critical"},
                        "annotations": {"summary": resumen, "description": detalle}}],
            "commonLabels": {"alertname": "SLOBurnRate", "service": host}}

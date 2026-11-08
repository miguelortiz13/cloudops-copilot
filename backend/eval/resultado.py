"""Formato común de los resultados de eval (`--json <ruta>`), el que publica eval/publicar.py."""

import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def guardar(suite: str, casos: List[Dict[str, Any]], objetivo: float = 0.9) -> Optional[Dict[str, Any]]:
    """Si se pidió `--json <ruta>`, deja ahí el resultado de la suite. Devuelve el resumen."""
    aciertos = sum(1 for c in casos if c["ok"])
    resumen = {"suite": suite, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "cases": len(casos),
               "passed": aciertos, "accuracy": round(aciertos / len(casos), 3) if casos else None, "target": objetivo,
               "invented_numbers": sum(len(c.get("invented", [])) for c in casos),
               "details": [{k: c.get(k) for k in ("name", "ok", "invented", "reason")} for c in casos]}
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w", encoding="utf-8") as f:
            json.dump(resumen, f, ensure_ascii=False, indent=1)
    return resumen

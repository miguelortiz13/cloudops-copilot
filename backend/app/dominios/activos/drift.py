"""
Drift de Terraform (fase 3 del plan 10): diferencias entre lo que dicen los estados y lo que hay en la nube.

Dos señales, solo de Azure (en AWS, Resource Explorer no indexa todos los tipos y daría falsos positivos):

- **Borrado fuera de Terraform**: un recurso de primer nivel que un estado gestiona y que ya no está en el
  inventario de una suscripción que la plataforma sí ve. Los recursos hijos (subredes, reglas, asignaciones)
  no cuentan: el inventario no los lista.
- **Tags cambiadas a mano**: las tags del estado no coinciden con las reales (nombres sin distinguir
  mayúsculas, como Azure).

Lo calcula el paso `drift` del job diario (con el índice de estados en caché) y lo deja en
DATA_DIR/drift.json: el panel lo lee sin abrir la base.
"""

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import select

from app.core import config
from app.db.models import Account, Resource

_PRIMER_NIVEL = re.compile(r"^/subscriptions/([^/]+)/resourcegroups/[^/]+/providers/([^/]+)/[^/]+/[^/]+$")
# Tienen forma de recurso de primer nivel pero el inventario (Resource Graph `resources`) no los lista:
# asignaciones de rol, bloqueos y políticas, y despliegues. Sin excluirlos serían falsos "borrados".
FUERA_DEL_INVENTARIO = {"microsoft.authorization", "microsoft.resources"}
MAX = 500


def _ruta():
    return config.DATA_DIR / "drift.json"


def calcular(session, indice: Dict[str, Any], ahora: datetime) -> Dict[str, Any]:
    suscripciones = {a.native_id.lower() for a in session.scalars(select(Account).where(Account.provider == "azure"))}
    vivos = {r.uid: r for r in session.scalars(select(Resource).where(Resource.provider == "azure", Resource.deleted_at.is_(None)))}
    borrados: List[Dict[str, Any]] = []
    tags: List[Dict[str, Any]] = []
    for rid in sorted(indice.get("managed_ids") or ()):
        m = _PRIMER_NIVEL.match(rid)
        if not m or m.group(1) not in suscripciones or m.group(2) in FUERA_DEL_INVENTARIO:
            continue
        uid = f"azure:{rid}"
        r = vivos.get(uid)
        if r is None:
            borrados.append({"id": rid, "name": rid.rsplit("/", 1)[-1], "terraform_type": indice.get("type_by_id", {}).get(rid)})
            continue
        en_estado = indice.get("tags_by_id", {}).get(rid)
        if en_estado is None:
            continue
        reales = {k.lower(): (k, str(v)) for k, v in (r.tags or {}).items()}
        declaradas = {k.lower(): (k, v) for k, v in en_estado.items()}
        cambios = [{"tag": (declaradas.get(k) or reales.get(k))[0], "terraform": declaradas.get(k, (None, None))[1],
                    "real": reales.get(k, (None, None))[1]}
                   for k in sorted(set(reales) | set(declaradas)) if declaradas.get(k, (0, None))[1] != reales.get(k, (0, None))[1]]
        if cambios:
            tags.append({"uid": uid, "name": r.name, "type": r.canonical_type or r.native_type, "changes": cambios})
    return {"generated_at": ahora.isoformat(timespec="seconds"), "states_read": indice.get("states_read", 0),
            "deleted": borrados[:MAX], "tags": tags[:MAX], "totals": {"deleted": len(borrados), "tags": len(tags)}}


def guardar(datos: Dict[str, Any]) -> None:
    ruta = _ruta()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False))
    temporal.replace(ruta)


def leer() -> Dict[str, Any]:
    try:
        return {"available": True, **json.loads(_ruta().read_text())}
    except (FileNotFoundError, ValueError):
        return {"available": False, "deleted": [], "tags": [], "totals": {"deleted": 0, "tags": 0}}


def recolectar(ctx, session):
    """Paso `drift` del job diario."""
    from app.collectors.common import Resultado

    tfstate = getattr(ctx.proveedor, "_tfstate", None)
    if tfstate is None:
        return Resultado(status="parcial", detail={"reason": "Sin estados de Terraform configurados (TFSTATE_ACCOUNT)."})
    indice = tfstate.get_index()
    if not indice.get("available"):
        return Resultado(status="parcial", detail={"reason": f"Estados no disponibles: {indice.get('reason') or 'sin estados legibles'}"})
    datos = calcular(session, indice, ctx.momento or datetime.now(timezone.utc))
    guardar(datos)
    return Resultado(items=datos["totals"]["deleted"] + datos["totals"]["tags"], detail=datos["totals"])

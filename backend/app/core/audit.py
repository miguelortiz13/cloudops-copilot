"""
Registro de auditoria.

Cada accion que cambia algo o actua sobre la nube deja una linea JSON en el
log (siempre) y una fila en `audit_log` (si hay base). Escribir en la base
despierta Azure SQL: es aceptable porque estas acciones las hace una persona,
pocas veces al dia, nunca un proceso periodico.

Un fallo al auditar nunca bloquea la accion: se informa en el log.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.authz import Usuario
from app.db import engine as db

# Una escritura de auditoria no debe dejar esperando al usuario mientras la
# base se reanuda; si no responde en este plazo, queda solo en el log.
ESPERA_SEGUNDOS = 45


def auditar(usuario: Usuario, accion: str, objetivo: Optional[str] = None,
            detalle: Optional[Dict[str, Any]] = None, resultado: str = "ok") -> None:
    registro = {
        "at": datetime.now(timezone.utc).isoformat(), "actor": usuario.actor, "actor_oid": usuario.oid or None,
        "role": usuario.rol, "action": accion, "target": (objetivo or "")[:450] or None,
        "outcome": resultado, "detail": detalle or {},
    }
    print("[audit] " + json.dumps(registro, ensure_ascii=False, default=str))
    if not db.is_configured():
        return
    try:
        from app.db.models import AuditLog

        with db.session_scope(ESPERA_SEGUNDOS) as s:
            s.add(AuditLog(**{**registro, "at": datetime.fromisoformat(registro["at"])}))
    except Exception as exc:
        print(f"[audit] No se pudo guardar en la base ({type(exc).__name__}): {exc}")


class auditado:
    """
    Audita un bloque con su resultado:

        with auditado(usuario, "k8s.chat", objetivo=cluster):
            ...

    Un error se registra como `error` y se vuelve a lanzar.
    """

    def __init__(self, usuario: Usuario, accion: str, objetivo: Optional[str] = None,
                 detalle: Optional[Dict[str, Any]] = None):
        self.args = (usuario, accion, objetivo, detalle or {})

    def __enter__(self):
        return self

    def __exit__(self, tipo, exc, tb):
        usuario, accion, objetivo, detalle = self.args
        if exc is not None:
            detalle = {**detalle, "error": f"{tipo.__name__}: {exc}"[:500]}
        auditar(usuario, accion, objetivo, detalle, "error" if exc is not None else "ok")
        return False

"""
Plataforma → Ajustes: las reglas y umbrales de cada dominio (app/core/ajustes.py).

Leer es de cualquier rol; cambiar y deshacer, de Administrador. Cada cambio queda en el
historial de ajustes (con el antes y el después) y en la auditoría.
"""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.core import ajustes
from app.core.audit import auditar
from app.core.authz import Usuario, requiere

router = APIRouter(tags=["plataforma"])


def _seccion(nombre: str) -> Dict[str, Any]:
    valores = ajustes.seccion(nombre)
    return {"values": valores, "defaults": ajustes._defecto(nombre), "origin": ajustes.origen(nombre),
            "schema": {k: list(ajustes.ESQUEMA[k]) for k in valores}}


@router.get("/api/settings")
def ver():
    """Todas las secciones con su valor, su valor por defecto, su origen (ajuste, variable o defecto) y su esquema."""
    return {"sections": {n: _seccion(n) for n in ajustes.SECCIONES}}


@router.put("/api/settings/{nombre}")
def cambiar(nombre: str, body: Dict[str, Any], usuario: Usuario = requiere("administrador")):
    if nombre not in ajustes.SECCIONES:
        raise HTTPException(status_code=404, detail=f"No existe la sección de ajustes {nombre!r}.")
    antes = ajustes.seccion(nombre)
    try:
        valores = ajustes.guardar(nombre, body, usuario.actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    auditar(usuario, f"ajustes.{nombre}", detalle={"antes": {k: antes[k] for k in body if k in antes}, "despues": body})
    return _seccion(nombre) | {"values": valores}


@router.get("/api/settings-history")
def historial():
    return {"items": ajustes.historial()}


@router.post("/api/settings-history/{indice}/undo")
def deshacer(indice: int, usuario: Usuario = requiere("administrador")):
    """Vuelve la sección de ese cambio a como estaba antes. El deshacer también queda en el historial."""
    try:
        e = ajustes.historial()[indice] if 0 <= indice < len(ajustes.historial()) else None
        valores = ajustes.deshacer(indice, usuario.actor)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    auditar(usuario, "ajustes.deshacer", objetivo=e["seccion"] if e else None, detalle={"volvio_a": e["antes"] if e else None})
    return {"section": e["seccion"] if e else None, "values": valores}


@router.get("/api/notifications")
def avisos_enviados(dias: int = 7):
    """Operación → Avisos: lo que publicó el motor de avisos en los últimos `dias` (máx. 90) y qué decidió."""
    from app.core import avisos

    items = avisos.registro(max(1, min(dias, 90)))
    return {"mode": ajustes.seccion("avisos")["modo"], "items": items[:500],
            "stats": {"total": len(items), "enviados": sum(e["enviado"] for e in items),
                      "silenciados": sum(e["decision"] == "silenciado" for e in items),
                      "duplicados": sum(e["decision"] == "duplicado" for e in items),
                      "filtrados": sum(e["decision"] == "filtrado" for e in items),
                      "fallidos": sum(bool(e["error"]) for e in items)}}



@router.get("/api/checks")
def chequeos():
    """Las URLs de Plataforma → Ajustes → Chequeos con su última respuesta (las revisa k8s-watch cada 10 minutos)."""
    from app.collectors import chequeos as modulo

    estado = modulo.leer_estado()
    return {"items": [{"url": u, **estado.get(u, {"ok": None})} for u in ajustes.seccion("chequeos")["urls"]]}

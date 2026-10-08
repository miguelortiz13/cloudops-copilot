"""
Modelos de lenguaje de la plataforma.

    from app import llm
    if llm.disponible():
        r = llm.generar("agente.chat", sistema, mensaje)

Sin proveedor configurado (`LLM_PROVIDER=none` o sin clave), `disponible()` es
falso y los agentes responden con el motor de reglas. Cada llamada deja una
linea `[llm]` con proveedor, modelo, tokens y duracion: es la medicion del
consumo hasta que haya un panel para eso.
"""

import json
import threading
from typing import Optional

from app.core import config
from app.llm.base import LLM, LLMError, Respuesta

__all__ = ["LLMError", "Respuesta", "disponible", "generar", "proveedor", "reiniciar"]

_proveedor: Optional[LLM] = None
_iniciado = False
_lock = threading.Lock()


def proveedor() -> Optional[LLM]:
    global _proveedor, _iniciado
    if _iniciado:
        return _proveedor
    with _lock:
        if not _iniciado:
            nombre = config.LLM_PROVIDER
            if nombre == "gemini" and config.GEMINI_API_KEY:
                from app.llm.gemini import Gemini

                _proveedor = Gemini(config.GEMINI_API_KEY, config.GEMINI_MODEL, config.LLM_TIMEOUT_SECONDS)
            elif nombre not in ("gemini", "none"):
                print(f"[llm] Proveedor desconocido '{nombre}': se usa el motor de reglas.")
            _iniciado = True
    return _proveedor


def reiniciar(nuevo: Optional[LLM] = None) -> None:
    """Pruebas: fija un proveedor (o ninguno)."""
    global _proveedor, _iniciado
    with _lock:
        _proveedor, _iniciado = nuevo, True


def disponible() -> bool:
    return proveedor() is not None


def generar(uso: str, sistema: str, mensaje: str, temperatura: float = 0.2, json_: bool = False,
            max_tokens: Optional[int] = None, usuario: Optional[str] = None) -> Respuesta:
    p = proveedor()
    if p is None:
        raise LLMError("No hay un modelo de lenguaje configurado.")
    try:
        r = p.generar(sistema, mensaje, temperatura=temperatura, json=json_, max_tokens=max_tokens)
    except LLMError as exc:
        print("[llm] " + json.dumps({"uso": uso, "proveedor": p.nombre, "modelo": p.modelo, "usuario": usuario,
                                     "ok": False, "error": str(exc)[:300]}, ensure_ascii=False))
        raise
    print("[llm] " + json.dumps({"uso": uso, "proveedor": p.nombre, "modelo": r.modelo, "usuario": usuario, "ok": True,
                                 "tokens_entrada": r.tokens_entrada, "tokens_salida": r.tokens_salida,
                                 "segundos": r.segundos}, ensure_ascii=False))
    return r

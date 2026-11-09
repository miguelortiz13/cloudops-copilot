"""
Motor de agentes con herramientas (docs/plan/09-agentes-ia.md, etapa A).

El modelo decide qué herramienta usar, recibe el resultado y sigue hasta
responder. Las herramientas son de solo lectura y devuelven datos acotados con un
enlace a la vista del panel que los respalda (la cita). Topes por ejecución:
llamadas a herramientas y tiempo total; al alcanzarlos se le pide la respuesta
final sin herramientas.
"""

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app import llm
from app.ai import guardas
from app.core import trazas
from app.llm.base import LLMError

MAX_LLAMADAS = 8
PRESUPUESTO_SEGUNDOS = 90
# Un resultado enorme diluye la señal y cuesta tokens: las herramientas ya acotan, esto es la red.
MAX_CARACTERES_RESULTADO = 30_000


@dataclass
class Herramienta:
    nombre: str
    descripcion: str
    parametros: Dict[str, Any]  # JSON Schema de los argumentos
    funcion: Callable[..., Dict[str, Any]]

    def declaracion(self) -> Dict[str, Any]:
        return {"nombre": self.nombre, "descripcion": self.descripcion, "parametros": self.parametros}


def ejecutar(h: Optional[Herramienta], argumentos: Dict[str, Any]) -> Dict[str, Any]:
    if h is None:
        return {"error": "Herramienta desconocida."}
    argumentos, error = guardas.validar(h.parametros, argumentos)
    if error:
        return {"error": error}
    try:
        resultado = h.funcion(**argumentos)
    except TypeError as exc:
        return {"error": f"Argumentos inválidos: {exc}"}
    except Exception as exc:  # la herramienta falla, el agente sigue y lo dice
        return {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    texto = json.dumps(resultado, ensure_ascii=False, default=str)
    if len(texto) > MAX_CARACTERES_RESULTADO:
        return {"error": "Resultado demasiado grande: usa filtros más específicos.", "caracteres": len(texto)}
    return resultado


def responder(sistema: str, pregunta: str, herramientas: List[Herramienta], uso: str,
              usuario: Optional[str] = None, max_llamadas: int = MAX_LLAMADAS,
              presupuesto_segundos: float = PRESUPUESTO_SEGUNDOS) -> Dict[str, Any]:
    """{answer, tools: [{nombre, argumentos, error?}], tokens, trace_id}. LLMError si el modelo falla."""
    p = llm.proveedor()
    if not llm.con_herramientas():
        raise LLMError("El modelo configurado no admite herramientas.")
    por_nombre = {h.nombre: h for h in herramientas}
    declaraciones = [h.declaracion() for h in herramientas]
    historial = p.iniciar(pregunta)
    traza: List[Dict[str, Any]] = []
    tokens = {"entrada": 0, "salida": 0}
    inicio = time.monotonic()
    traza_id, empezo, spans = trazas.nuevo_id(), datetime.now(timezone.utc), []
    try:
        while True:
            agotado = len(traza) >= max_llamadas or time.monotonic() - inicio > presupuesto_segundos
            t0 = time.monotonic()
            paso = p.paso(sistema + guardas.REGLA, historial, [] if agotado else declaraciones)
            spans.append(trazas.span_modelo(p.modelo, len(spans), paso.tokens_entrada, paso.tokens_salida,
                                            int((time.monotonic() - t0) * 1000), len(paso.llamadas or [])))
            tokens["entrada"] += paso.tokens_entrada or 0
            tokens["salida"] += paso.tokens_salida or 0
            if not paso.llamadas:
                break
            resultados = []
            for llamada in paso.llamadas:
                t0 = time.monotonic()
                dato = ejecutar(por_nombre.get(llamada.nombre), llamada.argumentos)
                spans.append(trazas.span_herramienta(llamada.nombre, llamada.argumentos, dato, int((time.monotonic() - t0) * 1000)))
                traza.append({"nombre": llamada.nombre, "argumentos": llamada.argumentos,
                              **({"error": dato["error"]} if "error" in dato else {})})
                resultados.append((llamada, guardas.envolver(dato)))
            p.agregar_resultados(historial, resultados)
    except LLMError as exc:
        _registrar(uso, p, usuario, traza, tokens, inicio, error=str(exc))
        trazas.registrar(traza_id, "invoke_agent", uso, p.nombre, p.modelo, usuario, empezo, int((time.monotonic() - inicio) * 1000),
                         tokens["entrada"], tokens["salida"], spans, error=str(exc))
        raise
    _registrar(uso, p, usuario, traza, tokens, inicio)
    trazas.registrar(traza_id, "invoke_agent", uso, p.nombre, p.modelo, usuario, empezo, int((time.monotonic() - inicio) * 1000),
                     tokens["entrada"], tokens["salida"], spans, respuesta_chars=len(paso.texto or ""))
    return {"answer": paso.texto, "tools": traza, "tokens": tokens, "trace_id": traza_id}


def _registrar(uso, p, usuario, traza, tokens, inicio, error: Optional[str] = None) -> None:
    print("[llm] " + json.dumps({"uso": uso, "proveedor": p.nombre, "modelo": p.modelo, "usuario": usuario,
                                 "ok": error is None, "herramientas": [t["nombre"] for t in traza],
                                 "tokens_entrada": tokens["entrada"], "tokens_salida": tokens["salida"],
                                 "segundos": round(time.monotonic() - inicio, 2),
                                 **({"error": error[:300]} if error else {})}, ensure_ascii=False))

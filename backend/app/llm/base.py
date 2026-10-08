"""
Interfaz comun para modelos de lenguaje.

Los agentes (chat, IaC, Kubernetes) piden texto con `generar()` y no conocen
el SDK del proveedor. Hoy hay una implementacion (Gemini, google-genai); Azure
OpenAI o Claude serian otra clase con el mismo metodo.

Toda falla del proveedor se traduce a `LLMError`, y cada agente decide su
respaldo (normalmente, el motor de reglas).
"""

from dataclasses import dataclass
from typing import Optional, Protocol


class LLMError(RuntimeError):
    """El proveedor no respondio o respondio algo inutilizable."""


@dataclass
class Respuesta:
    texto: str
    modelo: str
    tokens_entrada: Optional[int] = None
    tokens_salida: Optional[int] = None
    segundos: float = 0.0


class LLM(Protocol):
    nombre: str
    modelo: str

    def generar(self, sistema: str, mensaje: str, temperatura: float = 0.2,
                json: bool = False, max_tokens: Optional[int] = None) -> Respuesta:
        """Una respuesta a `mensaje` con las instrucciones `sistema`."""
        ...

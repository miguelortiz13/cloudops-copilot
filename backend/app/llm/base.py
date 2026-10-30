"""
Interfaz comun para modelos de lenguaje.

Los agentes (chat, IaC, Kubernetes) piden texto con `generar()` y no conocen
el SDK del proveedor. Hoy hay una implementacion (Gemini, google-genai); Azure
OpenAI o Claude serian otra clase con el mismo metodo.

Toda falla del proveedor se traduce a `LLMError`, y cada agente decide su
respaldo (normalmente, el motor de reglas).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


class LLMError(RuntimeError):
    """El proveedor no respondio o respondio algo inutilizable."""


@dataclass
class Respuesta:
    texto: str
    modelo: str
    tokens_entrada: Optional[int] = None
    tokens_salida: Optional[int] = None
    segundos: float = 0.0


@dataclass
class Llamada:
    """El modelo pide ejecutar una herramienta."""

    nombre: str
    argumentos: Dict[str, Any]


@dataclass
class Paso:
    """Un turno del modelo con herramientas: texto final o llamadas a herramientas."""

    texto: Optional[str]
    llamadas: List[Llamada] = field(default_factory=list)
    tokens_entrada: Optional[int] = None
    tokens_salida: Optional[int] = None


class LLM(Protocol):
    nombre: str
    modelo: str

    def generar(self, sistema: str, mensaje: str, temperatura: float = 0.2,
                json: bool = False, max_tokens: Optional[int] = None) -> Respuesta:
        """Una respuesta a `mensaje` con las instrucciones `sistema`."""
        ...


class LLMConHerramientas(LLM, Protocol):
    """
    Proveedor que sabe llamar funciones (app/ai). El historial es del proveedor
    (cada SDK guarda cosas propias, como las firmas de razonamiento de Gemini):
    el motor solo lo pasa de un turno al siguiente.
    """

    def iniciar(self, mensaje: str) -> List[Any]: ...

    def paso(self, sistema: str, historial: List[Any], herramientas: List[Dict[str, Any]]) -> Paso:
        """Un turno; agrega al historial lo que respondió el modelo. `herramientas` = [{nombre, descripcion, parametros}]."""
        ...

    def agregar_resultados(self, historial: List[Any], resultados: List[tuple]) -> None:
        """Agrega los resultados [(Llamada, dict)] para el siguiente turno."""
        ...

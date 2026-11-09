"""Gemini con el SDK `google-genai` (reemplaza a `google-generativeai`, sin soporte)."""

import time
from typing import List, Optional

from app.llm.base import Llamada, LLMError, Paso, Respuesta


class Gemini:
    nombre = "gemini"

    def __init__(self, api_key: str, modelo: str, timeout_segundos: int = 60):
        from google import genai
        from google.genai import types

        self.modelo = modelo
        self._types = types
        self._cliente = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_segundos * 1000))

    def generar(self, sistema: str, mensaje: str, temperatura: float = 0.2,
                json: bool = False, max_tokens: Optional[int] = None) -> Respuesta:
        config = self._types.GenerateContentConfig(
            system_instruction=sistema,
            temperature=temperatura,
            max_output_tokens=max_tokens,
            response_mime_type="application/json" if json else None,
        )
        inicio = time.monotonic()
        try:
            r = self._cliente.models.generate_content(model=self.modelo, contents=mensaje, config=config)
        except Exception as exc:
            raise LLMError(f"Gemini no respondió: {type(exc).__name__}: {str(exc)[:300]}") from exc
        texto = (getattr(r, "text", None) or "").strip()
        if not texto:
            motivo = getattr((r.candidates or [None])[0], "finish_reason", None) if getattr(r, "candidates", None) else None
            raise LLMError(f"Gemini devolvió una respuesta vacía (motivo: {motivo}).")
        uso = getattr(r, "usage_metadata", None)
        return Respuesta(
            texto=texto, modelo=self.modelo,
            tokens_entrada=getattr(uso, "prompt_token_count", None),
            tokens_salida=getattr(uso, "candidates_token_count", None),
            segundos=round(time.monotonic() - inicio, 2),
        )

    # ------------------------------------------------------------ embeddings (app/ai/conocimiento.py)

    def embeber(self, textos: List[str], consulta: bool = False, modelo: str = "gemini-embedding-001",
                dimension: int = 768) -> List[List[float]]:
        """Un vector por texto, en lotes de 100 (el máximo por llamada)."""
        config = self._types.EmbedContentConfig(task_type="RETRIEVAL_QUERY" if consulta else "RETRIEVAL_DOCUMENT",
                                                output_dimensionality=dimension)
        vectores: List[List[float]] = []
        for i in range(0, len(textos), 100):
            try:
                r = self._cliente.models.embed_content(model=modelo, contents=textos[i:i + 100], config=config)
            except Exception as exc:
                raise LLMError(f"Gemini no generó embeddings: {type(exc).__name__}: {str(exc)[:300]}") from exc
            if len(r.embeddings) != len(textos[i:i + 100]):
                raise LLMError(f"El modelo {modelo} devolvió {len(r.embeddings)} vectores para {len(textos[i:i + 100])} textos.")
            vectores += [list(e.values) for e in r.embeddings]
        return vectores

    # ------------------------------------------------------------ herramientas (app/ai)

    def iniciar(self, mensaje: str) -> list:
        return [self._types.Content(role="user", parts=[self._types.Part(text=mensaje)])]

    def paso(self, sistema: str, historial: list, herramientas: list) -> Paso:
        t = self._types
        declaraciones = [t.FunctionDeclaration(name=h["nombre"], description=h["descripcion"],
                                               parameters_json_schema=h["parametros"]) for h in herramientas]
        config = t.GenerateContentConfig(system_instruction=sistema, temperature=0.2,
                                         tools=[t.Tool(function_declarations=declaraciones)] if declaraciones else None,
                                         automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True))
        try:
            r = self._cliente.models.generate_content(model=self.modelo, contents=historial, config=config)
        except Exception as exc:
            raise LLMError(f"Gemini no respondió: {type(exc).__name__}: {str(exc)[:300]}") from exc
        candidato = (r.candidates or [None])[0]
        if candidato is None or candidato.content is None:
            raise LLMError(f"Gemini devolvió una respuesta vacía (motivo: {getattr(candidato, 'finish_reason', None)}).")
        # Se guarda el contenido tal cual: Gemini 3 exige recibir de vuelta sus firmas de razonamiento.
        historial.append(candidato.content)
        llamadas = [Llamada(nombre=fc.name, argumentos=dict(fc.args or {})) for fc in (r.function_calls or [])]
        uso = getattr(r, "usage_metadata", None)
        texto = None if llamadas else ((getattr(r, "text", None) or "").strip() or None)
        if not llamadas and not texto:
            raise LLMError(f"Gemini devolvió una respuesta vacía (motivo: {getattr(candidato, 'finish_reason', None)}).")
        return Paso(texto=texto, llamadas=llamadas, tokens_entrada=getattr(uso, "prompt_token_count", None),
                    tokens_salida=getattr(uso, "candidates_token_count", None))

    def agregar_resultados(self, historial: list, resultados: list) -> None:
        t = self._types
        historial.append(t.Content(role="user", parts=[t.Part.from_function_response(name=llamada.nombre, response=dato)
                                                       for llamada, dato in resultados]))

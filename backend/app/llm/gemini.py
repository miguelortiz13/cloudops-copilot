"""Gemini con el SDK `google-genai` (reemplaza a `google-generativeai`, sin soporte)."""

import time
from typing import Optional

from app.llm.base import LLMError, Respuesta


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

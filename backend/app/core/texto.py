"""Normalizacion de texto para comparar preguntas con palabras clave."""

import unicodedata


def normalizar(texto: str) -> str:
    """Minusculas y sin tildes: "¿Cuántos recursos?" -> "¿cuantos recursos?"."""
    descompuesto = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in descompuesto if not unicodedata.combining(c))

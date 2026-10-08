"""
Limite de uso del modelo por usuario.

Cada pregunta al chat, al agente de Kubernetes o al generador de IaC con IA
cuesta tokens. El limite evita que un usuario (o un script con su token)
agote la cuota del proveedor o dispare el gasto.

Ventanas deslizantes de una hora y de un dia, en memoria: el API corre con una
sola replica y un reinicio (escala a cero) las vacia, lo que solo puede
devolver cupo antes de tiempo, nunca negarlo de mas. Si el API escala a varias
replicas, el limite debe pasar a la base o a un almacen compartido.
"""

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple

from app.core import config

HORA, DIA = 3600, 86400


class LimiteExcedido(Exception):
    def __init__(self, mensaje: str, reintentar_en: int):
        super().__init__(mensaje)
        self.reintentar_en = reintentar_en


_uso: Dict[str, Deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def _limites() -> Tuple[int, int]:
    return config.LLM_MAX_REQUESTS_PER_HOUR, config.LLM_MAX_REQUESTS_PER_DAY


def consumir(usuario: str, ahora: Optional[float] = None) -> Dict[str, int]:
    """Registra una peticion o lanza LimiteExcedido. Devuelve lo que queda."""
    ahora = time.time() if ahora is None else ahora
    por_hora, por_dia = _limites()
    with _lock:
        marcas = _uso[usuario]
        while marcas and marcas[0] <= ahora - DIA:
            marcas.popleft()
        en_hora = [t for t in marcas if t > ahora - HORA]
        if por_dia and len(marcas) >= por_dia:
            espera = int(marcas[0] + DIA - ahora) + 1
            raise LimiteExcedido(f"Llegaste al límite de {por_dia} consultas al modelo por día.", espera)
        if por_hora and len(en_hora) >= por_hora:
            espera = int(en_hora[0] + HORA - ahora) + 1
            raise LimiteExcedido(f"Llegaste al límite de {por_hora} consultas al modelo por hora.", espera)
        marcas.append(ahora)
        return {"hora": por_hora - len(en_hora) - 1 if por_hora else -1,
                "dia": por_dia - len(marcas) if por_dia else -1}


def reiniciar() -> None:
    with _lock:
        _uso.clear()


def exigir_cupo(usuario: str) -> None:
    """
    Para los endpoints: consume una consulta del usuario o responde 429.

    Solo cuenta si hay un modelo configurado: las respuestas del motor de
    reglas no cuestan y no tienen limite.
    """
    from fastapi import HTTPException

    from app import llm

    if not llm.disponible():
        return
    try:
        consumir(usuario)
    except LimiteExcedido as exc:
        minutos = max(1, round(exc.reintentar_en / 60))
        raise HTTPException(
            status_code=429,
            detail=f"{exc} Vuelve a intentarlo en {minutos} min.",
            headers={"Retry-After": str(exc.reintentar_en)},
        )

"""
Chequeo determinista de cifras (plan 11, hito IA-1): toda cifra de una respuesta tiene que estar en los
datos que recibió el modelo. Sin otro modelo de por medio: barato y sin falsos aprobados por "parecer bien".

Se aceptan las cifras **derivadas**: la suma o la diferencia de dos cifras de los datos (04:30 − 04:18 =
"12 minutos", 98 + 1 = "99 pasos"). Se ignoran a propósito los enteros menores que 10 (numeración de
listas, conteos chicos) y los porcentajes (una variación calculada con dos cifras que sí están).
"""

import json
import re
from typing import Any, List, Set

_NUMERO = re.compile(r"(?<![\w.,])(\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,](\d+))?(?![\w])(\s*%)?")


def _valores(entero: str, decimales: str) -> Set[float]:
    """Interpretaciones posibles: 1.460 (miles o decimal), 3,20 (coma decimal), 0.0019."""
    limpio = re.sub(r"[.,]", "", entero)
    salida = {float(limpio + ("." + decimales if decimales else ""))}
    if re.fullmatch(r"\d{1,3}[.,]\d{3}", entero) and not decimales:
        salida.add(float(entero.replace(",", ".")))
    return salida


def numeros(texto: str) -> List[tuple]:
    return [(m.group(0).strip(), _valores(m.group(1), m.group(2) or ""), bool(m.group(3))) for m in _NUMERO.finditer(texto)]


def _en_datos(valor: float, datos: Set[float]) -> bool:
    return any(abs(valor - d) <= max(0.01, abs(d) * 0.005) or round(d, 1) == valor or round(d) == valor for d in datos)


def inventadas(texto: str, datos: Any) -> List[str]:
    """Las cifras de `texto` que no aparecen (con redondeo) en `datos`."""
    fuente = datos if isinstance(datos, str) else json.dumps(datos, ensure_ascii=False, default=str)
    base = sorted({v for _, vals, _ in numeros(fuente) for v in vals})[:400]
    disponibles = set(base) | {a + b for a in base for b in base} | {abs(a - b) for a in base for b in base}
    salida = []
    for crudo, vals, porcentaje in numeros(texto):
        if porcentaje or all(v < 10 and float(v).is_integer() for v in vals):
            continue
        if not any(_en_datos(v, disponibles) for v in vals):
            salida.append(crudo)
    return salida


def _prueba() -> None:
    datos = {"total_usd": 7.0, "semana_anterior_usd": 3.5, "servicios": [["Storage", 4.1]], "fecha": "2026-10-09", "filas": 1460}
    assert inventadas("Gasto: 7.00 USD (+100 %), Storage 4,10 el 09-10; 1.460 filas; 3 alertas.", datos) == []
    assert inventadas("Gasto: 12,40 USD y 2.300 filas.", datos) == ["12,40", "2.300"]
    # Derivadas: 7,0 − 3,5 = 3,50; 7,0 + 4,1 = 11,10.
    assert inventadas("Subió 3,50 USD; con Storage suman 11,10.", datos) == []


_prueba()

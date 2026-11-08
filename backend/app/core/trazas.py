"""
Trazas de IA (plan 11, hito IA-1): qué hizo cada ejecución del modelo, con la convención semántica de
OpenTelemetry para IA generativa (https://opentelemetry.io/docs/specs/semconv/gen-ai/).

Una traza por respuesta del agente (`invoke_agent`) o por llamada directa al modelo (`chat`): el span raíz
con los totales y un span por turno del modelo y por herramienta (tokens, latencia, tamaño del resultado,
error). Se guardan en DATA_DIR/trazas/AAAA-MM.jsonl, sin abrir la base y sin servicio externo; las lee
Plataforma → IA. No se guarda el texto de la pregunta ni de la respuesta: solo su tamaño.
"""

import json
import secrets
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.core import config

# Dominio de cada uso del modelo (el prefijo de `uso`), para agrupar en Plataforma → IA.
DOMINIO = {"asistente": "inicio", "resumen": "inicio", "agente": "inicio", "chat": "inicio", "activos": "activos",
           "k8s": "activos", "iac": "activos", "costos": "costos", "riesgo": "riesgo", "incidente": "operacion"}
MAX_ARGUMENTO = 200


def dominio_de(uso: str) -> str:
    return DOMINIO.get(uso.split(".", 1)[0], "plataforma")


def nuevo_id() -> str:
    return secrets.token_hex(16)


def _carpeta():
    return config.DATA_DIR / "trazas"


def _corto(valor: Any) -> Any:
    texto = json.dumps(valor, ensure_ascii=False, default=str)
    return valor if len(texto) <= MAX_ARGUMENTO else texto[:MAX_ARGUMENTO] + "…"


def span_herramienta(nombre: str, argumentos: Dict[str, Any], resultado: Dict[str, Any], ms: int) -> Dict[str, Any]:
    return {"name": f"execute_tool {nombre}", "duration_ms": ms, "attributes": {
        "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": nombre,
        "cloudops.tool.arguments": {k: _corto(v) for k, v in argumentos.items()},
        "cloudops.tool.result_chars": len(json.dumps(resultado, ensure_ascii=False, default=str)),
        **({"error.type": str(resultado["error"])[:200]} if "error" in resultado else {})}}


def span_modelo(modelo: str, turno: int, entrada: Optional[int], salida: Optional[int], ms: int, llamadas: int) -> Dict[str, Any]:
    return {"name": f"chat {modelo}", "duration_ms": ms, "attributes": {
        "gen_ai.operation.name": "chat", "gen_ai.request.model": modelo, "cloudops.turn": turno,
        "gen_ai.usage.input_tokens": entrada or 0, "gen_ai.usage.output_tokens": salida or 0, "cloudops.tool_calls": llamadas}}


def registrar(traza_id: str, operacion: str, uso: str, proveedor: str, modelo: str, usuario: Optional[str], inicio: datetime,
              ms: int, entrada: int, salida: int, spans: List[Dict[str, Any]], error: Optional[str] = None,
              respuesta_chars: Optional[int] = None) -> None:
    """Deja la traza en el registro. Nunca lanza: perder una traza no debe tumbar una respuesta."""
    traza = {"trace_id": traza_id, "name": f"{operacion} {uso}", "start": inicio.isoformat(timespec="milliseconds"),
             "duration_ms": ms, "attributes": {
                 "gen_ai.operation.name": operacion, "gen_ai.system": proveedor, "gen_ai.request.model": modelo,
                 "gen_ai.usage.input_tokens": entrada, "gen_ai.usage.output_tokens": salida,
                 "cloudops.use": uso, "cloudops.domain": dominio_de(uso), "enduser.id": usuario,
                 **({"cloudops.response_chars": respuesta_chars} if respuesta_chars is not None else {}),
                 **({"error.type": error[:300]} if error else {})},
             "spans": spans}
    try:
        carpeta = _carpeta()
        carpeta.mkdir(parents=True, exist_ok=True)
        # shortcut: append sin bloqueo entre procesos, como el registro de avisos; pasar a una tabla si crece.
        with open(carpeta / f"{inicio:%Y-%m}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(traza, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        print(f"[trazas] No se pudo guardar la traza {traza_id}: {exc}")


def leer(dias: int = 7, ahora: Optional[datetime] = None) -> List[Dict[str, Any]]:
    ahora = ahora or datetime.now(timezone.utc)
    desde = (ahora - timedelta(days=dias)).isoformat()
    meses = sorted({(ahora - timedelta(days=d)).strftime("%Y-%m") for d in range(0, dias + 1, 28)} | {ahora.strftime("%Y-%m")})
    filas: List[Dict[str, Any]] = []
    for mes in meses:
        try:
            with open(_carpeta() / f"{mes}.jsonl", encoding="utf-8") as f:
                filas += [json.loads(linea) for linea in f if linea.strip()]
        except FileNotFoundError:
            continue
    return sorted((t for t in filas if t["start"] >= desde), key=lambda t: t["start"], reverse=True)


def _percentil(valores: List[int], p: float) -> Optional[int]:
    if not valores:
        return None
    valores = sorted(valores)
    return valores[min(len(valores) - 1, int(round(p * (len(valores) - 1))))]


def resumen(trazas: List[Dict[str, Any]], precio_entrada: float, precio_salida: float) -> Dict[str, Any]:
    """Por dominio y por uso: llamadas, errores, tokens, costo estimado, latencia p50/p95 y herramientas más usadas."""
    def costo(t: Dict[str, Any]) -> float:
        a = t["attributes"]
        return (a["gen_ai.usage.input_tokens"] * precio_entrada + a["gen_ai.usage.output_tokens"] * precio_salida) / 1_000_000

    def bloque(grupo: List[Dict[str, Any]]) -> Dict[str, Any]:
        ms = [t["duration_ms"] for t in grupo]
        return {"calls": len(grupo), "errors": sum(1 for t in grupo if "error.type" in t["attributes"]),
                "input_tokens": sum(t["attributes"]["gen_ai.usage.input_tokens"] for t in grupo),
                "output_tokens": sum(t["attributes"]["gen_ai.usage.output_tokens"] for t in grupo),
                "cost_usd": round(sum(costo(t) for t in grupo), 4), "p50_ms": _percentil(ms, 0.5), "p95_ms": _percentil(ms, 0.95)}

    por: Dict[str, Dict[str, List[Dict[str, Any]]]] = {"domain": {}, "use": {}}
    herramientas: Dict[str, Dict[str, int]] = {}
    for t in trazas:
        por["domain"].setdefault(t["attributes"]["cloudops.domain"], []).append(t)
        por["use"].setdefault(t["attributes"]["cloudops.use"], []).append(t)
        for s in t["spans"]:
            if s["attributes"]["gen_ai.operation.name"] == "execute_tool":
                h = herramientas.setdefault(s["attributes"]["gen_ai.tool.name"], {"calls": 0, "errors": 0})
                h["calls"] += 1
                h["errors"] += "error.type" in s["attributes"]
    return {"total": bloque(trazas), "by_domain": {k: bloque(v) for k, v in sorted(por["domain"].items())},
            "by_use": {k: bloque(v) for k, v in sorted(por["use"].items())},
            "tools": sorted(({"name": k, **v} for k, v in herramientas.items()), key=lambda h: -h["calls"]),
            "priced": bool(precio_entrada or precio_salida), "median_ms": statistics.median([t["duration_ms"] for t in trazas]) if trazas else None}

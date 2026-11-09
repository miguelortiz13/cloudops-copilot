"""
Base de conocimiento (plan 11, hito IA-4): recuperación sobre lo que no son datos estructurados.

Corpus:
- **runbooks** y la **guía del panel** (`backend/conocimiento/**/*.md`, uno por sección `##`);
- **catálogo de controles**: cada regla con su riesgo, detección y remediación;
- **incidentes resueltos** con diagnóstico marcado como correcto o cerrados como solucionados, con sus notas y
  su post-mortem (lo que de verdad pasó y cómo se resolvió);
- **excepciones de control** vigentes con su justificación.

Índice en `DATA_DIR/conocimiento/indice.json`: cada fragmento con su vector (Gemini, 768 dimensiones) y un hash;
al reindexar solo se generan los vectores de lo que cambió. Búsqueda **híbrida**: BM25 sobre las palabras (para
nombres exactos como `ImagePullBackOff` o `redis-cart`) y similitud de vectores (para lo que se dice distinto),
combinadas por *reciprocal rank fusion*. Sin modelo o sin vectores, queda la parte léxica.
"""

import hashlib
import json
import math
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.core import config

RAIZ = Path(__file__).resolve().parents[2] / "conocimiento"
DIMENSION = 768
MAX_FRAGMENTO = 2000
TIPOS = ["runbook", "guia", "control", "incidente", "excepcion"]
Embebedor = Callable[[List[str], bool], List[List[float]]]


# ---------------------------------------------------------------- corpus

def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()[:16]


def _fragmento(tipo: str, fuente: str, titulo: str, texto: str, enlace: Optional[str]) -> Dict[str, Any]:
    texto = texto.strip()[:MAX_FRAGMENTO]
    return {"id": fuente, "tipo": tipo, "fuente": fuente, "titulo": titulo, "texto": texto, "enlace": enlace,
            "hash": _hash(f"{titulo}\n{texto}")}


def _markdown(ruta: Path, tipo: str) -> List[Dict[str, Any]]:
    contenido = ruta.read_text(encoding="utf-8")
    titulo = next((linea[2:].strip() for linea in contenido.splitlines() if linea.startswith("# ")), ruta.stem)
    partes = re.split(r"\n(?=## )", contenido)
    rel = ruta.relative_to(RAIZ).as_posix()
    salida = []
    for n, parte in enumerate(partes):
        seccion = parte.splitlines()[0][3:].strip() if parte.startswith("## ") else "Introducción"
        cuerpo = parte.split("\n", 1)[1] if parte.startswith("## ") else parte.replace(f"# {titulo}", "", 1)
        if cuerpo.strip():
            salida.append(_fragmento(tipo, f"conocimiento/{rel}#{n}", f"{titulo} · {seccion}", cuerpo, None))
    return salida


def _documentos() -> List[Dict[str, Any]]:
    return [f for ruta in sorted(RAIZ.rglob("*.md"))
            for f in _markdown(ruta, "guia" if ruta.parent.name == "guia" else "runbook")]


def _catalogo() -> List[Dict[str, Any]]:
    from app.compliance import catalog

    salida = []
    for r in catalog.REGLAS.values():
        controles = "; ".join(f"{m} {c}" for m, cs in r.frameworks.items() for c, _ in cs)
        texto = (f"Regla {r.id} ({r.proveedor}, severidad {r.severity_default}). {r.description}\nDetección: {r.detection}\n"
                 f"Remediación: {r.remediation}\nControles: {controles}")
        salida.append(_fragmento("control", f"catalogo/{r.id}", r.title, texto, "#/riesgo/hallazgos"))
    return salida


def _de_la_base() -> List[Dict[str, Any]]:
    from sqlalchemy import or_, select

    from app.db import engine as db
    from app.db.models import ControlException, Incident, IncidentEvent

    if not db.is_configured():
        return []
    salida = []
    with db.session_scope() as s:
        incidentes = s.scalars(select(Incident).where(
            Incident.status.in_(("resuelto", "cerrado")), Incident.diagnosis.is_not(None), Incident.parent_id.is_(None),
            or_(Incident.feedback == "correcto", Incident.closed_reason == "solucionado"),
            or_(Incident.feedback.is_(None), Incident.feedback != "incorrecto")).order_by(Incident.id.desc()).limit(500)).all()
        notas: Dict[int, List[str]] = {}
        if incidentes:
            for e in s.scalars(select(IncidentEvent).where(IncidentEvent.incident_id.in_([i.id for i in incidentes]),
                                                           IncidentEvent.kind == "nota")):
                notas.setdefault(e.incident_id, []).append(e.text)
        for i in incidentes:
            alertas = "; ".join(f"{a.get('name')}: {a.get('summary') or ''}" for a in (i.alerts or [])[:5])
            texto = (f"Incidente #{i.id} en el clúster {i.cluster or '-'}, severidad {i.severity}, abierto "
                     f"{i.opened_at:%Y-%m-%d}. Alertas: {alertas}\nDiagnóstico: {(i.diagnosis or '')[:1000]}\n"
                     f"Cierre: {i.closed_reason or i.status}; diagnóstico marcado: {i.feedback or 'sin marcar'}.\n"
                     + (f"Notas: {' | '.join(notas.get(i.id, []))[:400]}\n" if notas.get(i.id) else "")
                     + (f"Post-mortem: {i.postmortem[:500]}" if i.postmortem else ""))
            salida.append(_fragmento("incidente", f"incidente/{i.id}", f"Incidente #{i.id}: {i.title}", texto,
                                     f"#/operacion/incidentes/{i.id}"))
        hoy = datetime.now(timezone.utc).date()
        for x in s.scalars(select(ControlException).where(ControlException.revoked_at.is_(None), ControlException.until >= hoy)):
            salida.append(_fragmento("excepcion", f"excepcion/{x.id}", f"Excepción aprobada {x.framework} {x.control}",
                                     f"Hasta {x.until.isoformat()}, aprobada por {x.created_by}. Justificación: {x.justification}",
                                     "#/riesgo/cumplimiento"))
    return salida


def corpus() -> List[Dict[str, Any]]:
    return _documentos() + _catalogo() + _de_la_base()


# ---------------------------------------------------------------- índice

def _ruta() -> Path:
    return config.DATA_DIR / "conocimiento" / "indice.json"


def _embebedor() -> Optional[Embebedor]:
    from app import llm

    p = llm.proveedor()
    if p is None or not hasattr(p, "embeber"):
        return None
    return lambda textos, consulta: p.embeber(textos, consulta, config.GEMINI_EMBEDDING_MODEL, DIMENSION)


_cache: Dict[str, Any] = {"mtime": None, "indice": None, "sin_indice": None, "hasta": 0.0}


def cargar() -> Optional[Dict[str, Any]]:
    """El índice guardado (releído solo si cambió el archivo), o None."""
    try:
        mtime = _ruta().stat().st_mtime
    except FileNotFoundError:
        return None
    if _cache["mtime"] != mtime:
        _cache["indice"], _cache["mtime"] = json.loads(_ruta().read_text(encoding="utf-8")), mtime
    return _cache["indice"]


def reindexar(embeber: Optional[Embebedor] = None) -> Dict[str, Any]:
    """Arma el corpus, reutiliza los vectores de lo que no cambió y genera los que faltan."""
    embeber = embeber if embeber is not None else _embebedor()
    previo = cargar() or {}
    modelo = config.GEMINI_EMBEDDING_MODEL if embeber else None
    reusables = {c["hash"]: c["vector"] for c in previo.get("chunks", []) if c.get("vector")} if previo.get("modelo") == modelo else {}
    chunks = corpus()
    faltan = [c for c in chunks if c["hash"] not in reusables]
    error = None
    if embeber and faltan:
        try:
            for c, v in zip(faltan, embeber([f"{c['titulo']}\n{c['texto']}" for c in faltan], False)):
                reusables[c["hash"]] = v
        except Exception as exc:  # sin vectores nuevos el índice sigue sirviendo por palabras
            error = f"{type(exc).__name__}: {str(exc)[:200]}"
    for c in chunks:
        if c["hash"] in reusables:
            c["vector"] = [round(x, 6) for x in reusables[c["hash"]]]
    indice = {"modelo": modelo, "dimension": DIMENSION, "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "chunks": chunks}
    ruta = _ruta()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(indice, ensure_ascii=False), encoding="utf-8")
    temporal.replace(ruta)
    return {**estado(indice), "nuevos": len(faltan), **({"error": error} if error else {})}


def estado(indice: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    indice = indice or cargar()
    if not indice:
        return {"indexado": False}
    chunks = indice["chunks"]
    return {"indexado": True, "modelo": indice["modelo"], "actualizado": indice["actualizado"], "fragmentos": len(chunks),
            "con_vector": sum(1 for c in chunks if c.get("vector")), "por_tipo": dict(Counter(c["tipo"] for c in chunks))}


# ---------------------------------------------------------------- búsqueda

_VACIAS = set("para por con sin que los las del una uno como esta este cuando donde desde hasta sobre entre cual "
              "qué cómo cuál hay son fue ser the and".split())


def _palabras(texto: str) -> List[str]:
    plano = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    salida = []
    for p in re.findall(r"[a-z0-9][a-z0-9._:-]*[a-z0-9]", plano):
        # El nombre completo (redis-cart, v9.9.9) y sus partes (redis, cart): así coincide quien escribe solo una.
        salida += [x for x in {p, *re.split(r"[._:-]", p)} if len(x) >= 3 and x not in _VACIAS]
    return salida


def _bm25(consulta: str, chunks: List[Dict[str, Any]], k1: float = 1.5, b: float = 0.75) -> List[float]:
    docs = [Counter(_palabras(f"{c['titulo']} {c['texto']}")) for c in chunks]
    largo = sum(sum(d.values()) for d in docs) / max(1, len(docs))
    terminos = set(_palabras(consulta))
    df = {t: sum(1 for d in docs if t in d) for t in terminos}
    n = len(docs)
    return [sum(math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) * d[t] * (k1 + 1) /
                (d[t] + k1 * (1 - b + b * sum(d.values()) / largo)) for t in terminos if d.get(t))
            for d in docs]


def _coseno(a: List[float], b: List[float]) -> float:
    # shortcut: Python puro sobre unos cientos de fragmentos (milisegundos); pasar a numpy o a VECTOR de SQL si el corpus crece.
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def _sin_indice() -> Dict[str, Any]:
    """Sin índice guardado, el corpus en memoria (sin vectores), renovado cada 10 minutos."""
    if _cache["sin_indice"] is None or time.monotonic() > _cache["hasta"]:
        _cache["sin_indice"], _cache["hasta"] = {"modelo": None, "chunks": corpus()}, time.monotonic() + 600
    return _cache["sin_indice"]


def buscar(consulta: str, tipo: Optional[str] = None, k: int = 5, embeber: Optional[Embebedor] = None) -> Dict[str, Any]:
    """Los `k` fragmentos más útiles. `embeber`: None usa el modelo configurado; False, solo palabras."""
    indice = cargar() or _sin_indice()
    chunks = [c for c in indice["chunks"] if not tipo or c["tipo"] == tipo]
    if not chunks or not consulta.strip():
        return {"modo": "vacío", "resultados": []}
    rankings = []
    lexico = _bm25(consulta, chunks)
    rankings.append(sorted((i for i, s in enumerate(lexico) if s > 0), key=lambda i: -lexico[i])[:20])
    modo = "léxico"
    embeber = embeber if embeber is not None else (_embebedor() if indice.get("modelo") == config.GEMINI_EMBEDDING_MODEL else None)
    if embeber and any(c.get("vector") for c in chunks):
        try:
            q = embeber([consulta], True)[0]
            similitud = [_coseno(q, c["vector"]) if c.get("vector") else -1.0 for c in chunks]
            rankings.append(sorted(range(len(chunks)), key=lambda i: -similitud[i])[:20])
            modo = "híbrido"
        except Exception as exc:  # el modelo falla: queda la parte léxica
            print(f"[conocimiento] Sin vector de la consulta: {type(exc).__name__}: {str(exc)[:200]}")
    rrf: Dict[int, float] = {}
    for ranking in rankings:
        for pos, i in enumerate(ranking):
            rrf[i] = rrf.get(i, 0.0) + 1 / (60 + pos)
    mejores = sorted(rrf, key=lambda i: -rrf[i])[:k]
    return {"modo": modo, "resultados": [{k_: chunks[i][k_] for k_ in ("tipo", "titulo", "fuente", "enlace", "texto")}
                                         for i in mejores]}


def recolectar(ctx, session):
    """Paso del job diario: reindexa lo que cambió."""
    from app.collectors.common import Resultado

    r = reindexar()
    return Resultado(items=r.get("fragmentos", 0), status="parcial" if r.get("error") else "ok", detail=r)

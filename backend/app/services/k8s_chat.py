"""
Chat SRE de Kubernetes sobre la última foto del agente (docs/plan/08-kubernetes.md, parte 4).

El modelo recibe lo mismo que muestra la página: incidencias, pods con problemas
con sus últimas líneas de log, cargas degradadas, nodos y eventos. No ejecuta
nada en el clúster: sugiere comandos `kubectl` para que una persona los corra.
Sin modelo, responde con las incidencias y su siguiente paso.
"""

import json
from typing import Dict, List, Optional

from app import llm
from app.core import config

MAX_EVENTOS = 15
MAX_LINEAS_LOG = 20


def elegir(pregunta: str, pedido: Optional[str], resumenes: List[Dict]) -> Optional[str]:
    """Entre los que reportan: el pedido, el que nombra la pregunta o el primero."""
    resumenes = [r for r in resumenes if r.get("reporting")]
    nombres = [r["name"] for r in resumenes]
    if pedido in nombres:
        return pedido
    texto = pregunta.lower()
    for r in resumenes:
        if r["name"].lower() in texto:
            return r["name"]
    return nombres[0] if nombres else None


def contexto(d: Dict) -> Dict:
    return {
        "cluster": d["name"], "distribucion": d.get("distribution"), "version": d.get("version"),
        "foto_tomada": d.get("collected_at"), "foto_vieja": d.get("stale"),
        "salud": d.get("health"), "nodos_listos": f"{d.get('nodes_ready')}/{d.get('nodes')}",
        "pods_en_ejecucion": f"{d.get('pods_running')}/{d.get('pods')}",
        "incidencias": d["incident_list"],
        "pods_con_problemas": [{**{k: v for k, v in p.items() if k != "log"},
                                "log": ({**p["log"], "lines": p["log"]["lines"][-MAX_LINEAS_LOG:]} if p.get("log") else None)}
                               for p in d["problem_pods"]],
        "cargas_degradadas": [{k: v for k, v in w.items() if k != "security"} for w in d["workload_list"] if w["ready"] < w["desired"]],
        "nodos": [{k: n.get(k) for k in ("name", "ready", "pressure", "roles", "kubelet", "cpu_m", "memory_mib")}
                  for n in d["node_list"]],
        "eventos_recientes": d["events"][:MAX_EVENTOS],
    }


def _sin_modelo(d: Dict, motivo: str) -> str:
    lineas = [f"## {d['name']} · salud {d.get('health')}/100",
              f"Nodos listos {d.get('nodes_ready')}/{d.get('nodes')} · pods en ejecución {d.get('pods_running')}/{d.get('pods')}", ""]
    if d["incident_list"]:
        lineas += [f"- **[{i['severity']}] {i['title']}**: {i['detail']}. `{i['recommendation']}`" for i in d["incident_list"]]
    else:
        lineas.append("Sin incidencias en la última foto.")
    return "\n".join(lineas + ["", f"*{motivo}*"])


def responder(pregunta: str, d: Dict, usuario: Optional[str] = None) -> Dict:
    resumen = {"cluster": d["name"], "health": d.get("health"), "incidents": d.get("incidents"),
               "collected_at": d.get("collected_at")}
    if not llm.disponible():
        return {"answer": _sin_modelo(d, "Sin modelo de lenguaje configurado: se muestra el estado del clúster."),
                "mode": "rules", "context_summary": resumen}
    sistema = (
        f"Eres el agente SRE de Kubernetes de {config.ORG_NAME}. Respondes en español, en Markdown y con brevedad, "
        "usando solo el contexto JSON: es la última foto que envió el agente de solo lectura del clúster, con su hora. "
        "No puedes ejecutar nada en el clúster. Cuando haya un problema, explica la causa probable citando la "
        "evidencia (motivo, reinicios, líneas de log, eventos) y sugiere comandos kubectl concretos para confirmarlo o "
        "corregirlo. Si la foto está vieja, adviértelo. Si el contexto no alcanza para responder, dilo.")
    try:
        r = llm.generar("k8s.chat", sistema,
                        f"Contexto:\n{json.dumps(contexto(d), ensure_ascii=False)}\n\nPregunta: {pregunta}", usuario=usuario)
        return {"answer": r.texto, "mode": f"llm_{llm.proveedor().nombre}", "context_summary": resumen}
    except llm.LLMError:
        return {"answer": _sin_modelo(d, "El modelo de lenguaje no respondió; se muestra el estado del clúster."),
                "mode": "fallback", "context_summary": resumen}

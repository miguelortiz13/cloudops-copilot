"""
Eval de recuperación de la base de conocimiento (plan 11, hito IA-4).

Preguntas sembradas, dichas como las diría alguien de guardia (sin copiar el texto de los documentos),
cada una con la fuente que debe aparecer entre los 5 primeros resultados: runbooks, guía del panel,
catálogo de controles e incidentes resueltos sembrados en una base temporal. Mide **recall@5**
(objetivo 80 %) con la búsqueda híbrida real y, como referencia, con la parte léxica sola.
Usa el modelo real de embeddings (centavos):

    cd backend && GEMINI_API_KEY=... python -m eval.recuperacion [--json resultado.json]
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

TMP = tempfile.mkdtemp(prefix="eval-recuperacion-")
os.environ.setdefault("LLM_PROVIDER", "gemini")
os.environ["DATABASE_URL"] = f"sqlite:///{TMP}/eval.db"
os.environ["DATA_DIR"] = TMP

from app import llm  # noqa: E402
from app.ai import conocimiento  # noqa: E402
from app.db import engine as db  # noqa: E402
from app.db.models import Base, Incident, IncidentEvent  # noqa: E402
from eval import resultado  # noqa: E402

AHORA = datetime.now(timezone.utc)
RB = "conocimiento/runbooks/"

INCIDENTES = [
    (101, "KubePodCrashLooping · boutique · cartservice", "Causa probable: cartservice no alcanza redis-cart:6379 (Connection refused); "
     "el pod de redis-cart estaba en Pending por falta de memoria en el nodo.", "Se liberó memoria del nodo y redis-cart volvió; cartservice se recuperó solo."),
    (102, "KubeNodeNotReady · lab-worker2", "Causa probable: la máquina del laboratorio se reinició y el nodo lab-worker2 quedó NotReady; "
     "tormenta de 9 alertas de pods en varios namespaces.", "El nodo volvió al reiniciar Docker Desktop."),
    (103, "TargetDown · boutique · currencyservice", "Causa probable: el Service currencyservice usa el selector app=currency-service "
     "y los pods tienen app=currencyservice; 0 endpoints.", "Se corrigió el selector en el manifiesto."),
]

# (pregunta, fuentes que cuentan como acierto: prefijos)
PREGUNTAS = [
    ("el pod del carrito se reinicia una y otra vez y el log dice que no puede conectarse a redis", [f"{RB}k8s-crashloopbackoff", "incidente/101"]),
    ("después de desplegar, el contenedor arranca, tira una excepción de configuración y vuelve a morir", [f"{RB}k8s-crashloopbackoff"]),
    ("el pod no arranca porque no encuentra la imagen en el registro, el tag no existe", [f"{RB}k8s-imagepullbackoff"]),
    ("el contenedor termina con código de salida 137", [f"{RB}k8s-oomkilled"]),
    ("llegaron muchas alertas de pods al mismo tiempo en distintos namespaces y un worker no responde", [f"{RB}k8s-nodo-notready", "incidente/102"]),
    ("los pods están sanos pero el servicio responde 503 porque no tiene destinos", [f"{RB}k8s-servicio-sin-endpoints", "incidente/103"]),
    ("la nueva versión del deployment nunca termina de salir y conviven pods viejos y nuevos", [f"{RB}k8s-rollout-atascado"]),
    ("ayer el gasto de una suscripción se disparó sin motivo aparente", [f"{RB}costos-anomalia-y-presupuesto"]),
    ("vamos a pasarnos del presupuesto de este mes, qué hago", [f"{RB}costos-anomalia-y-presupuesto"]),
    ("tengo un hallazgo crítico pero no lo puedo corregir todavía, cómo lo dejo documentado", [f"{RB}riesgo-hallazgo-critico", "conocimiento/guia/"]),
    ("el job de las 6 de la mañana falló porque la base de datos estaba dormida", [f"{RB}plataforma-recolector-y-chequeos"]),
    ("cómo callo las alertas de un namespace mientras hago mantenimiento", ["conocimiento/guia/"]),
    ("cómo conecto Claude Code a la plataforma", ["conocimiento/guia/"]),
    ("dónde cambio el presupuesto mensual de AWS", ["conocimiento/guia/", f"{RB}costos-anomalia-y-presupuesto"]),
    ("un bucket de S3 se puede leer desde internet", ["catalogo/aws.storage.public-access-not-blocked"]),
    ("el puerto 22 está abierto a todo internet en un grupo de seguridad de red de Azure", ["catalogo/network.admin-port-open", f"{RB}riesgo-hallazgo-critico"]),
    ("hay contenedores que corren con privilegios de administrador del nodo", ["catalogo/k8s.workload.privileged", "catalogo/k8s.workload.run-as-root"]),
    ("la cuenta root de AWS no tiene segundo factor", ["catalogo/aws.identity.root-without-mfa"]),
]


def sembrar() -> None:
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    with db.session_scope() as s:
        for id_, titulo, diagnostico, nota in INCIDENTES:
            s.add(Incident(id=id_, key=f"k{id_}", source="alertmanager", cluster="lab", title=titulo, severity="alta", status="resuelto",
                           alerts=[{"name": titulo.split(" · ")[0], "summary": ""}], opened_at=AHORA - timedelta(days=5),
                           last_alert_at=AHORA, resolved_at=AHORA, diagnosis=diagnostico, feedback="correcto"))
            s.add(IncidentEvent(incident_id=id_, at=AHORA, actor="eval", kind="nota", text=nota))


def acierta(resultados, esperadas) -> int:
    """Posición (1..5) del primer resultado esperado, o 0."""
    return next((n for n, r in enumerate(resultados[:5], 1) if any(r["fuente"].startswith(e) for e in esperadas)), 0)


def main() -> int:
    p = llm.proveedor()
    if p is None or not hasattr(p, "embeber"):
        print("Falta GEMINI_API_KEY.")
        return 2
    sembrar()
    r = conocimiento.reindexar()
    print(f"Índice: {r['fragmentos']} fragmentos, {r['con_vector']} con vector {r.get('error') or ''}")
    casos, lexicos = [], 0
    for pregunta, esperadas in PREGUNTAS:
        hibrida = conocimiento.buscar(pregunta)
        pos = acierta(hibrida["resultados"], esperadas)
        lexicos += bool(acierta(conocimiento.buscar(pregunta, embeber=False)["resultados"], esperadas))  # False: sin vectores
        casos.append({"name": pregunta, "ok": bool(pos), "reason": None if pos else f"top 5: {[x['fuente'] for x in hibrida['resultados']]}"})
        print(f"[{'OK @' + str(pos) if pos else 'FALLA'}] ({hibrida['modo']}) {pregunta}" + ("" if pos else f"\n    {casos[-1]['reason']}"))
    res = resultado.guardar("recuperacion", casos, objetivo=0.8)
    print(f"recall@5 híbrido: {res['passed']}/{res['cases']} = {res['accuracy']:.0%} (objetivo: 80 %) · solo léxico: "
          f"{lexicos}/{len(PREGUNTAS)} = {lexicos / len(PREGUNTAS):.0%}")
    return 0 if res["accuracy"] >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())

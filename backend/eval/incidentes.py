"""
Evaluación del diagnóstico de incidentes (plan 09, etapa B).

Cinco incidentes sembrados con su causa conocida: la alerta de Alertmanager y la
foto del clúster en ese momento. El agente diagnostica con las herramientas de
verdad sobre esos datos y se verifica que la sección "Causa probable" nombre la causa
real (no los siguientes pasos ni el tono).
Usa el modelo real (gasta tokens):

    cd backend && GEMINI_API_KEY=... python -m eval.incidentes
"""

import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

TMP = tempfile.mkdtemp(prefix="eval-incidentes-")
os.environ.setdefault("LLM_PROVIDER", "gemini")
os.environ["DATABASE_URL"] = f"sqlite:///{TMP}/eval.db"
os.environ["DATA_DIR"] = TMP

from app import llm  # noqa: E402
from app.ai import agente, herramientas, incidentes  # noqa: E402
from app.core import config  # noqa: E402
from app.db import engine as db  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.services import k8s_fleet  # noqa: E402

AHORA = datetime.now(timezone.utc)
HACE = (AHORA - timedelta(minutes=4)).isoformat()


def nodo(nombre, listo=True):
    return {"name": nombre, "ready": listo, "pressure": [], "roles": ["worker"], "kubelet": "v1.37.0"}


def pod(nombre, ns="boutique", fase="Running", motivo=None, listos=0, reinicios=0, nodo_="n1", log=None, creado=None):
    p = {"namespace": ns, "name": nombre, "phase": fase, "reason": motivo, "ready": listos, "containers": 1,
         "restarts": reinicios, "node": nodo_, "owner_kind": "ReplicaSet", "owner": nombre.rsplit("-", 1)[0],
         "created": creado or (AHORA - timedelta(hours=3)).isoformat(), "last_restart": HACE if reinicios else None,
         "last_restart_reason": "Error" if reinicios else None}
    if log:
        p["log"] = {"container": "server", "previous": bool(reinicios), "lines": log}
    return p


def foto(pods, cargas, eventos, nodos=None, servicios=None):
    return {"cluster": "lab", "collected_at": HACE, "distribution": "kind", "kubernetes_version": "v1.37.0",
            "nodes": nodos or [nodo("n1"), nodo("n2")], "namespaces": ["boutique"], "pods": pods, "workloads": cargas,
            "services": servicios or [], "events": eventos}


def carga(nombre, deseadas, listas):
    return {"kind": "Deployment", "namespace": "boutique", "name": nombre, "desired": deseadas, "ready": listas}


def evento(obj, motivo, mensaje):
    return {"namespace": "boutique", "kind": "Pod", "name": obj, "reason": motivo, "message": mensaje, "count": 12, "last": HACE}


def alerta(nombre, objetivo, resumen, severidad="warning"):
    return [{"name": nombre, "status": "firing", "severity": incidentes.SEVERIDAD.get(severidad, "media"),
             "labels": {"alertname": nombre, "namespace": "boutique", "pod": objetivo, "severity": severidad},
             "summary": resumen, "description": "", "starts_at": HACE, "ends_at": ""}]


ESCENARIOS = [
    ("CrashLoop porque no alcanza la base",
     foto([pod("cartservice-7d9f-x1", motivo="CrashLoopBackOff", reinicios=14,
               log=["Starting cart service", "Error: Connection refused (redis-cart:6379)", "Unhandled exception, exiting"])],
          [carga("cartservice", 1, 0), carga("redis-cart", 1, 0)],
          [evento("cartservice-7d9f-x1", "BackOff", "Back-off restarting failed container server")],
          servicios=[{"namespace": "boutique", "name": "redis-cart", "type": "ClusterIP", "selector": True,
                      "headless": False, "endpoints": 0}]),
     alerta("KubePodCrashLooping", "cartservice-7d9f-x1", "Pod is crash looping."),
     [r"redis", r"6379|conex|connection"]),
    ("Imagen inexistente después de un despliegue",
     foto([pod("paymentservice-5c4b-q2", fase="Pending", motivo="ImagePullBackOff", creado=(AHORA - timedelta(minutes=30)).isoformat())],
          [carga("paymentservice", 1, 0)],
          [evento("paymentservice-5c4b-q2", "Failed",
                  "Failed to pull image \"us-central1-docker.pkg.dev/boutique/paymentservice:v9.9.9\": not found")]),
     alerta("KubePodNotReady", "paymentservice-5c4b-q2", "Pod has been in a non-ready state for more than 15 minutes."),
     [r"imagen|image", r"v9\.9\.9|no existe|not found"]),
    ("Sin memoria (OOMKilled)",
     foto([pod("recommendationservice-6b8d-z9", motivo="OOMKilled", reinicios=9,
               log=["Loading catalog into memory", "Killed"])],
          [carga("recommendationservice", 1, 0)],
          [evento("recommendationservice-6b8d-z9", "BackOff", "Back-off restarting failed container server")]),
     alerta("KubePodCrashLooping", "recommendationservice-6b8d-z9", "Pod is crash looping."),
     [r"memoria|memory|OOM"]),
    ("Nodo caído",
     foto([pod("frontend-77c-a1", fase="Pending", creado=(AHORA - timedelta(minutes=25)).isoformat(), nodo_=None),
           pod("checkoutservice-5f-b2", fase="Unknown", nodo_="n2", creado=(AHORA - timedelta(hours=5)).isoformat())],
          [carga("frontend", 2, 1), carga("checkoutservice", 1, 0)],
          [{"namespace": None, "kind": "Node", "name": "n2", "reason": "NodeNotReady",
            "message": "Node n2 status is now: NodeNotReady", "count": 1, "last": HACE}],
          nodos=[nodo("n1"), nodo("n2", listo=False)]),
     alerta("KubeNodeNotReady", "n2", "Node n2 has been unready for more than 15 minutes.", "critical"),
     [r"\bn2\b", r"nodo|node"]),
    ("Servicio sin endpoints por un selector mal escrito",
     foto([pod("currencyservice-9d-c3", listos=1)], [carga("currencyservice", 1, 1)],
          [{"namespace": "boutique", "kind": "Endpoints", "name": "currencyservice", "reason": "FailedToUpdateEndpoint",
            "message": "No pods match selector app=currency-service", "count": 5, "last": HACE}],
          servicios=[{"namespace": "boutique", "name": "currencyservice", "type": "ClusterIP", "selector": True,
                      "headless": False, "endpoints": 0}]),
     alerta("TargetDown", "currencyservice", "100% of the currencyservice targets are down."),
     [r"selector", r"currency-service"]),
]


def main() -> int:
    if not llm.con_herramientas():
        print("Falta GEMINI_API_KEY (o el proveedor no admite herramientas).")
        return 2
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    k8s_fleet.configurados = lambda: ["lab"]
    aciertos = 0
    for nombre, f, alertas, esperado in ESCENARIOS:
        k8s_fleet.leer = lambda credenciales, cluster, f=f: f if cluster == "lab" else None
        i = SimpleNamespace(source="alertmanager", cluster="lab", title=f"{alertas[0]['name']} · boutique",
                            severity=alertas[0]["severity"], opened_at=AHORA, alerts=alertas)
        try:
            r = agente.responder(incidentes.SISTEMA.format(org=config.ORG_NAME), incidentes._mensaje(i),
                                 herramientas.para_asistente(None), uso="eval.incidente", usuario="eval")
            texto, usadas = r["answer"] or "", [t["nombre"] for t in r["tools"]]
        except llm.LLMError as exc:
            texto, usadas = f"(error: {exc})", []
        causa = re.search(r"Causa probable.*?(?=\*\*Evidencia|$)", texto, re.S | re.I)
        causa = causa.group(0) if causa else texto
        ok = all(re.search(p, causa, re.I) for p in esperado)
        aciertos += ok
        print(f"[{'OK' if ok else 'FALLA'}] {nombre}\n    herramientas: {usadas}\n    {causa.strip()[:280]!r}\n")
    print(f"Diagnósticos correctos: {aciertos}/{len(ESCENARIOS)} = {aciertos / len(ESCENARIOS):.0%} (objetivo: 90 %)")
    return 0 if aciertos / len(ESCENARIOS) >= 0.9 else 1


if __name__ == "__main__":
    sys.exit(main())

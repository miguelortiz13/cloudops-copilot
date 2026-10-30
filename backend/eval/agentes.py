"""
Conjunto de evaluación del asistente (plan 09, etapa A; criterio de salida de la
fase 3: 90 % de exactitud).

Siembra una base SQLite con datos conocidos y una foto de Kubernetes, hace
preguntas con respuesta verificable al motor con herramientas y cuenta cuántas
respuestas contienen lo esperado. Usa el modelo real (gasta tokens):

    cd backend && GEMINI_API_KEY=... python -m eval.agentes

No corre en cada PR: las pruebas del bucle usan un modelo simulado
(tests/unit/test_ai_agente.py).
"""

import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal

TMP = tempfile.mkdtemp(prefix="eval-agentes-")
os.environ.setdefault("LLM_PROVIDER", "gemini")
os.environ["DATABASE_URL"] = f"sqlite:///{TMP}/eval.db"
os.environ["DATA_DIR"] = TMP

from app import llm  # noqa: E402
from app.ai import asistente  # noqa: E402
from app.collectors.findings import _sincronizar_reglas  # noqa: E402
from app.db import engine as db  # noqa: E402
from app.db.models import Account, Base, CollectorRun, CostDaily, Finding, Resource  # noqa: E402
from app.services import k8s_fleet  # noqa: E402

AHORA = datetime.now(timezone.utc)
HOY = AHORA.date()

PREGUNTAS = [
    ("¿Cuántos hallazgos críticos activos hay en total?", [r"\b2\b"]),
    ("¿Qué recurso gastó más en los últimos 30 días y cuánto?", [r"vm-api", r"12[.,]40?"]),
    ("¿Qué cuenta tuvo el mayor gasto en los últimos 30 días?", [r"Producción"]),
    ("¿Qué recursos se crearon en la última semana fuera de Terraform y quién los creó?", [r"st-a-mano", r"ana@contoso\.test"]),
    ("¿Cuántos recursos de AWS hay en el inventario?", [r"\b3\b"]),
    ("¿Qué está fallando en el clúster lab-k8s y cuál es la causa probable?", [r"pagos", r"db:5432"]),
    ("¿Qué versión de Kubernetes tiene lab-k8s y hasta cuándo tiene soporte?", [r"1\.35", r"2027"]),
    ("¿Hay buckets de S3 que no estén gestionados por Terraform? ¿Cuáles?", [r"bucket-sin-tf"]),
]


def sembrar() -> None:
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    antes = AHORA - timedelta(days=60)
    with db.session_scope() as s:
        _sincronizar_reglas(s)
        s.add_all([
            Account(uid="azure:sub/prod", provider="azure", native_id="prod", name="Producción", first_seen=antes, last_seen=AHORA),
            Account(uid="azure:sub/lab", provider="azure", native_id="lab", name="Laboratorio", first_seen=antes, last_seen=AHORA),
            Account(uid="aws:account/1", provider="aws", native_id="1", name="AWS lab", first_seen=antes, last_seen=AHORA),
        ])
        s.flush()

        def recurso(cuenta, nombre, tipo, iac, creador=None, visto=antes):
            uid = f"{cuenta}/{nombre}"
            s.add(Resource(uid=uid, provider=cuenta.split(":")[0], account_uid=cuenta, name=nombre, native_type=tipo,
                           canonical_type=None, in_iac_state=iac, created_by=creador, first_seen=visto, last_seen=AHORA))
            return uid

        vm = recurso("azure:sub/prod", "vm-api", "microsoft.compute/virtualmachines", True)
        st = recurso("azure:sub/prod", "st-datos", "microsoft.storage/storageaccounts", True)
        recurso("azure:sub/lab", "st-a-mano", "microsoft.storage/storageaccounts", False, "ana@contoso.test",
                AHORA - timedelta(days=2))
        recurso("aws:account/1", "bucket-con-tf", "s3:bucket", True)
        recurso("aws:account/1", "bucket-sin-tf", "s3:bucket", False)
        recurso("aws:account/1", "rol-lectura", "iam:role", True)

        for i in range(1, 31):
            dia = HOY - timedelta(days=i)
            for uid, cuenta, monto in ((vm, "azure:sub/prod", "0.4133"), (st, "azure:sub/prod", "0.05"),
                                       ("aws:account/1/bucket-sin-tf", "aws:account/1", "0.02")):
                s.add(CostDaily(charge_date=dia, account_uid=cuenta, resource_uid=uid, service_name="svc",
                                billed_cost=Decimal(monto), effective_cost=Decimal(monto), currency="USD", source="query"))

        def hallazgo(regla, uid, cuenta, sev, estado="abierto"):
            s.add(Finding(rule_id=regla, resource_uid=uid, account_uid=cuenta, severity=sev, status=estado,
                          first_seen=antes, last_seen=AHORA, details={}))

        hallazgo("storage.public-blob-access", st, "azure:sub/prod", "critica")
        hallazgo("aws.identity.root-without-mfa", "aws:account/1", "aws:account/1", "critica")
        hallazgo("network.admin-port-open", vm, "azure:sub/prod", "critica", "resuelto")
        hallazgo("aws.storage.public-access-not-blocked", "aws:account/1/bucket-sin-tf", "aws:account/1", "alta")
        s.add(CollectorRun(collector="costs", started_at=AHORA, finished_at=AHORA, status="ok", items=1,
                           detail={"since": (HOY - timedelta(days=90)).isoformat()}))


def foto_lab():
    hace = (AHORA - timedelta(minutes=3)).isoformat()
    return {"cluster": "lab-k8s", "collected_at": hace, "distribution": "k3s", "kubernetes_version": "v1.35.5+k3s1",
            "nodes": [{"name": "n1", "ready": True, "pressure": [], "roles": ["control-plane"], "kubelet": "v1.35.5"}],
            "namespaces": ["tienda"],
            "workloads": [{"kind": "Deployment", "namespace": "tienda", "name": "pagos", "desired": 2, "ready": 0}],
            "pods": [{"namespace": "tienda", "name": "pagos-7d9f-x1", "phase": "Running", "reason": "CrashLoopBackOff",
                      "ready": 0, "containers": 1, "restarts": 14, "node": "n1", "owner_kind": "ReplicaSet",
                      "owner": "pagos-7d9f", "created": (AHORA - timedelta(hours=2)).isoformat(),
                      "last_restart": hace,
                      "log": {"container": "pagos", "previous": True,
                              "lines": ["iniciando", "ERROR: no se pudo conectar a db:5432 (connection refused)"]}}],
            "services": [{"namespace": "tienda", "name": "db", "type": "ClusterIP", "selector": True, "headless": False,
                          "endpoints": 0}],
            "events": [{"namespace": "tienda", "kind": "Pod", "name": "pagos-7d9f-x1", "reason": "BackOff",
                        "message": "Back-off restarting failed container", "count": 40, "last": hace}]}


def main() -> int:
    if not llm.con_herramientas():
        print("Falta GEMINI_API_KEY (o el proveedor no admite herramientas).")
        return 2
    sembrar()
    k8s_fleet.configurados = lambda: ["lab-k8s"]
    k8s_fleet.leer = lambda credenciales, nombre: foto_lab() if nombre == "lab-k8s" else None
    aciertos = 0
    for pregunta, esperado in PREGUNTAS:
        try:
            r = asistente.responder(pregunta, "inventory", None, usuario="eval")
            texto, usadas = r["answer"] or "", [t["nombre"] for t in r["tools"]]
        except llm.LLMError as exc:
            texto, usadas = f"(error: {exc})", []
        ok = all(re.search(p, texto, re.IGNORECASE) for p in esperado)
        aciertos += ok
        print(f"[{'OK' if ok else 'FALLA'}] {pregunta}\n    herramientas: {usadas}\n    {texto[:300]!r}\n")
    exactitud = aciertos / len(PREGUNTAS)
    print(f"Exactitud: {aciertos}/{len(PREGUNTAS)} = {exactitud:.0%} (objetivo: 90 %)")
    return 0 if exactitud >= 0.9 else 1


if __name__ == "__main__":
    sys.exit(main())

"""
Kubernetes como proveedor (parte 3 del plan del módulo): inventario y reglas k8s.*
sobre la foto del agente, con el mismo ciclo de vida de hallazgos que Azure y AWS.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.collectors import findings, inventory  # noqa: E402
from app.collectors.common import Contexto  # noqa: E402
from app.core import config  # noqa: E402
from app.db import engine as db  # noqa: E402
from app.db.models import Account, Base, Finding, Resource  # noqa: E402
from app.providers.kubernetes import KubernetesProvider  # noqa: E402

AHORA = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
CUENTA = "kubernetes:cluster/homelab"


def contenedor(nombre, imagen="nginx:1.27", **extra):
    return {"name": nombre, "image": imagen, "limits": True, "privileged": False, "no_escalation": True,
            "non_root": True, **extra}


def seguridad(*contenedores, **pod):
    return {"host_network": False, "host_pid": False, "host_ipc": False, "host_path": False,
            "containers": list(contenedores), **pod}


def foto(cargas, minutos=3):
    return {"cluster": "homelab", "collected_at": (AHORA - timedelta(minutes=minutos)).isoformat(),
            "distribution": "k3s", "kubernetes_version": "v1.35.5+k3s1",
            "nodes": [{"name": "n1", "roles": ["control-plane"]}], "workloads": cargas}


def carga(nombre, seg, ns="apps", kind="Deployment"):
    return {"kind": kind, "namespace": ns, "name": nombre, "desired": 1, "ready": 1, "security": seg}


def proveedor(*fotos_por_cluster, momento=AHORA):
    fotos = dict(fotos_por_cluster)
    return KubernetesProvider(lambda n: fotos.get(n), list(fotos), momento)


def test_cuentas_y_recursos_salen_de_la_foto():
    p = proveedor(("homelab", foto([carga("web", seguridad(contenedor("web")))])), ("viejo", foto([], minutos=25 * 60)),
                  ("sin-agente", None))
    assert [c.uid for c in p.cuentas()] == [CUENTA]  # el de foto vieja y el sin agente quedan fuera
    recursos = {r.uid: r for r in p.recursos([CUENTA])}
    assert recursos[CUENTA].canonical_type == "kubernetes.cluster" and recursos[CUENTA].tags["distribution"] == "k3s"
    assert recursos[f"{CUENTA}/node/n1"].native_type == "kubernetes/Node"
    web = recursos[f"{CUENTA}/ns/apps/deployment/web"]
    assert (web.name, web.group_name, web.native_type) == ("web", "apps", "apps/Deployment")


def test_reglas_sobre_las_banderas_de_cada_carga():
    cargas = [
        carga("sana", seguridad(contenedor("a"))),
        carga("mala", seguridad(contenedor("app", imagen="redis", limits=False, non_root=False),
                                contenedor("sidecar", privileged=True, no_escalation=False),
                                host_network=True, host_pid=True, host_path=True)),
        carga("latest", seguridad(contenedor("x", imagen="ghcr.io/org/app:latest"))),
        carga("digest", seguridad(contenedor("x", imagen="nginx@sha256:abc"))),
        carga("sistema", seguridad(contenedor("x", privileged=True)), ns="kube-system", kind="DaemonSet"),
    ]
    r = proveedor(("homelab", foto(cargas))).evaluar_reglas([CUENTA])
    por = {(h.rule_id, h.resource_uid.rsplit("/", 1)[-1]): h for h in r.hallazgos}
    assert set(por) == {
        ("k8s.workload.privileged", "mala"), ("k8s.workload.privilege-escalation", "mala"),
        ("k8s.workload.run-as-root", "mala"), ("k8s.workload.no-resource-limits", "mala"),
        ("k8s.workload.mutable-image-tag", "mala"), ("k8s.workload.host-namespaces", "mala"),
        ("k8s.workload.host-path", "mala"), ("k8s.workload.mutable-image-tag", "latest"),
    }
    assert por[("k8s.workload.privileged", "mala")].details["containers"] == ["sidecar"]
    assert por[("k8s.workload.host-namespaces", "mala")].details["shared"] == ["hostNetwork", "hostPID"]
    assert por[("k8s.workload.privileged", "mala")].severity == "alta" and r.reglas_sin_evidencia == frozenset()


def test_un_agente_anterior_no_resuelve_hallazgos():
    r = proveedor(("homelab", foto([{"kind": "Deployment", "namespace": "apps", "name": "web", "desired": 1, "ready": 1}])))\
        .evaluar_reglas([CUENTA])
    assert r.hallazgos == [] and "k8s.workload.privileged" in r.reglas_sin_evidencia


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'k.db'}")
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    yield
    db.reset_engine()


def correr(modulo, p, momento=AHORA):
    ctx = Contexto(azure=None, inventory=None, cost=None, secops=None, momento=momento, proveedor=p, cuentas=p.cuentas())
    with db.session_scope() as s:
        return modulo.recolectar(ctx, s)


def test_ciclo_de_vida_en_la_base(base):
    mala = carga("web", seguridad(contenedor("web", privileged=True)))
    p = proveedor(("homelab", foto([mala])))
    assert correr(inventory, p).items == 3  # clúster, nodo y carga
    correr(findings, p)
    with db.session_scope() as s:
        assert s.scalar(select(Account.provider).where(Account.uid == CUENTA)) == "kubernetes"
        h = s.scalars(select(Finding)).one()
        assert (h.rule_id, h.status, h.account_uid) == ("k8s.workload.privileged", "abierto", CUENTA)
        assert s.get(Resource, h.resource_uid).name == "web"

    # Corregida la carga, el hallazgo se resuelve solo.
    correr(findings, proveedor(("homelab", foto([carga("web", seguridad(contenedor("web")))]))))
    with db.session_scope() as s:
        assert s.scalars(select(Finding.status)).one() == "resuelto"


@pytest.mark.parametrize("version,estado,parche", [
    ("v1.35.5+k3s1", "vigente", "1.35.9"),
    ("v1.34.3-eks-ce1d5eb", "por_vencer", "1.34.12"),  # vence el 27-oct-2026
    ("v1.33.13", "sin_soporte", None),                  # ya en el último parche
    ("v1.99.0", "sin_dato", None),
    (None, "sin_dato", None),
])
def test_fin_de_soporte(version, estado, parche):
    from app.services import k8s_fleet

    s = k8s_fleet.soporte(version, AHORA)
    assert (s["status"], s["latest_patch"]) == (estado, parche)


def test_version_sin_soporte_o_por_vencer_es_hallazgo():
    def con_version(v):
        f = foto([])
        f["kubernetes_version"] = v
        return f

    r = proveedor(("homelab", con_version("v1.33.2"))).evaluar_reglas([CUENTA])
    h = r.hallazgos[0]
    assert (h.rule_id, h.resource_uid, h.severity) == ("k8s.cluster.unsupported-version", CUENTA, "alta")
    assert h.details == {"version": "v1.33.2", "end_of_support": "2026-06-28", "latest_patch": "1.33.13"}
    assert proveedor(("homelab", con_version("v1.34.12"))).evaluar_reglas([CUENTA]).hallazgos[0].severity == "media"
    assert proveedor(("homelab", con_version("v1.35.5+k3s1"))).evaluar_reglas([CUENTA]).hallazgos == []

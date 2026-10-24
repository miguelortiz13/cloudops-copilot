"""
Módulo de Kubernetes con agente (docs/plan/08-kubernetes.md): la foto que arma
el agente, su subida con la SAS y las incidencias que el API calcula de ella.
"""

import gzip
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import deps  # noqa: E402
from app.main import app  # noqa: E402
from app.services import k8s_fleet  # noqa: E402

AHORA = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
HACE_UNA_HORA = (AHORA - timedelta(hours=1)).isoformat()

_ruta = Path(__file__).resolve().parents[3] / "k8s-agent" / "agent.py"
_spec = importlib.util.spec_from_file_location("k8s_agent", _ruta)
agente = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agente)


class ApiFalsa:
    """El API de Kubernetes de un k3s con un pod en CrashLoop y un servicio sin pods."""

    RESPUESTAS = {
        "/version": {"gitVersion": "v1.31.4+k3s1"},
        "/api/v1/nodes": [{
            "metadata": {"name": "nodo1", "labels": {"node-role.kubernetes.io/control-plane": "true"},
                         "creationTimestamp": "2026-01-01T00:00:00Z"},
            "status": {"conditions": [{"type": "Ready", "status": "True"}, {"type": "DiskPressure", "status": "False"}],
                       "nodeInfo": {"kubeletVersion": "v1.31.4+k3s1", "osImage": "Ubuntu 24.04", "architecture": "arm64",
                                    "containerRuntimeVersion": "containerd://1.7"},
                       "capacity": {"cpu": "4", "memory": "8000000Ki"}}}],
        "/api/v1/namespaces": [{"metadata": {"name": "default"}}, {"metadata": {"name": "kube-system"}}],
        "/apis/apps/v1/deployments": [{"metadata": {"namespace": "default", "name": "web"},
                                       "spec": {"replicas": 2}, "status": {"readyReplicas": 1}}],
        "/apis/apps/v1/statefulsets": [],
        "/apis/apps/v1/daemonsets": [{"metadata": {"namespace": "kube-system", "name": "svclb"},
                                      "status": {"desiredNumberScheduled": 1, "numberReady": 1}}],
        "/api/v1/pods": [
            {"metadata": {"namespace": "default", "name": "web-1", "creationTimestamp": HACE_UNA_HORA,
                          "ownerReferences": [{"kind": "ReplicaSet", "name": "web-abc"}]},
             "spec": {"nodeName": "nodo1", "containers": [{"name": "web", "image": "nginx:latest",
                                                            "env": [{"name": "CLAVE", "value": "secreto"}]}]},
             "status": {"phase": "Running", "containerStatuses": [
                 {"ready": False, "restartCount": 12, "state": {"waiting": {"reason": "CrashLoopBackOff"}}}]}},
            {"metadata": {"namespace": "default", "name": "web-2", "creationTimestamp": HACE_UNA_HORA},
             "spec": {"containers": [{"name": "web", "image": "nginx:1.27", "resources": {"limits": {"cpu": "1"}}}]},
             "status": {"phase": "Running", "containerStatuses": [{"ready": True, "restartCount": 0, "state": {"running": {}}}]}},
            {"metadata": {"namespace": "default", "name": "migracion", "creationTimestamp": HACE_UNA_HORA},
             "spec": {"containers": [{"name": "m"}]}, "status": {"phase": "Succeeded"}},
        ],
        "/api/v1/services": [
            {"metadata": {"namespace": "default", "name": "web"}, "spec": {"type": "ClusterIP", "selector": {"app": "web"}}},
            {"metadata": {"namespace": "default", "name": "huerfano"}, "spec": {"type": "ClusterIP", "selector": {"app": "x"}}},
        ],
        "/apis/discovery.k8s.io/v1/endpointslices": [
            {"metadata": {"namespace": "default", "labels": {"kubernetes.io/service-name": "web"}},
             "endpoints": [{"conditions": {"ready": True}}, {"conditions": {"ready": False}}]}],
        "/api/v1/events": [
            {"metadata": {"namespace": "default"}, "involvedObject": {"kind": "Pod", "name": "web-1"}, "reason": "BackOff",
             "message": "Back-off restarting failed container", "count": 40, "lastTimestamp": "2026-10-24T11:59:00Z"}],
    }

    def __init__(self):
        self.consultas = []

    def get(self, ruta):
        return self.RESPUESTAS[ruta]

    def listar(self, ruta, **params):
        self.consultas.append((ruta, params))
        return iter(self.RESPUESTAS[ruta])


def test_la_foto_resume_el_cluster_sin_datos_sensibles():
    api = ApiFalsa()
    foto = agente.foto(api, "homelab")

    assert (foto["cluster"], foto["distribution"], foto["schema"]) == ("homelab", "k3s", 1)
    n = foto["nodes"][0]
    assert (n["ready"], n["roles"], n["cpu_m"], n["memory_mib"], n["pressure"]) == (True, ["control-plane"], 4000, 7812, [])
    web1 = next(p for p in foto["pods"] if p["name"] == "web-1")
    assert (web1["reason"], web1["restarts"], web1["ready"], web1["containers"]) == ("CrashLoopBackOff", 12, 0, 1)
    assert web1["images"] == [{"name": "web", "image": "nginx:latest", "limits": False, "privileged": False}]
    assert {s["name"]: s["endpoints"] for s in foto["services"]} == {"web": 1, "huerfano": 0}
    assert ("/api/v1/events", {"fieldSelector": "type=Warning"}) in api.consultas
    # Ni variables de entorno ni el spec completo viajan en la foto.
    assert "secreto" not in json.dumps(foto)


@pytest.mark.parametrize("version,etiquetas,esperada", [
    ("v1.30.5", {"kubernetes.azure.com/cluster": "x"}, "aks"),
    ("v1.30.5-eks-ce1d5eb", {}, "eks"),
    ("v1.30.4+rke2r1", {}, "rke2"),
    ("v1.30.5", {}, "kubernetes"),
])
def test_la_distribucion_se_detecta_por_version_y_etiquetas(version, etiquetas, esperada):
    assert agente.distribucion(version, [{"metadata": {"labels": etiquetas}}]) == esperada


def test_la_subida_escribe_latest_comprimido_y_el_error_no_muestra_la_sas(monkeypatch):
    enviadas = []

    class Respuesta:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(agente.urllib.request, "urlopen", lambda req, timeout: enviadas.append(req) or Respuesta())
    agente.subir("https://cuenta.blob.core.windows.net/k8s-homelab?sv=1&sig=SECRETO", {"cluster": "homelab"})
    req = enviadas[0]
    assert req.full_url == "https://cuenta.blob.core.windows.net/k8s-homelab/latest.json?sv=1&sig=SECRETO"
    assert (req.get_method(), req.get_header("X-ms-blob-type"), req.get_header("Content-encoding")) == ("PUT", "BlockBlob", "gzip")
    assert json.loads(gzip.decompress(req.data)) == {"cluster": "homelab"}

    def falla(req, timeout):
        raise agente.urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(agente.urllib.request, "urlopen", falla)
    with pytest.raises(RuntimeError) as error:
        agente.subir("https://cuenta.blob.core.windows.net/k8s-homelab?sig=SECRETO", {})
    assert "SECRETO" not in str(error.value) and "403" in str(error.value)


def foto_homelab():
    return {**agente.foto(ApiFalsa(), "homelab"), "collected_at": (AHORA - timedelta(minutes=3)).isoformat()}


def test_incidencias_y_salud_salen_de_la_foto():
    incid = k8s_fleet.incidencias(foto_homelab(), AHORA)
    assert [(i["severity"], i["title"]) for i in incid] == [
        ("critica", "CrashLoopBackOff: web-1"),
        ("media", "Deployment degradado: web"),
        ("media", "Servicio sin endpoints: huerfano"),
    ]
    assert k8s_fleet.salud(incid) == 100 - 25 - 4 - 4


def test_un_nodo_caido_y_un_pod_recien_creado():
    foto = foto_homelab()
    foto["nodes"][0]["ready"] = False
    foto["pods"].append({"namespace": "default", "name": "nuevo", "phase": "Pending", "reason": None, "ready": 0,
                         "containers": 1, "restarts": 0, "created": (AHORA - timedelta(minutes=2)).isoformat()})
    titulos = [i["title"] for i in k8s_fleet.incidencias(foto, AHORA)]
    assert titulos[0] == "Nodo sin responder: nodo1"
    # Pending hace 2 minutos todavía está arrancando.
    assert not any("nuevo" in t for t in titulos)


def test_el_resumen_marca_la_foto_vieja():
    foto = foto_homelab()
    assert k8s_fleet.resumen("homelab", foto, AHORA)["stale"] is False
    foto["collected_at"] = (AHORA - timedelta(minutes=20)).isoformat()
    r = k8s_fleet.resumen("homelab", foto, AHORA)
    assert (r["stale"], r["nodes_ready"], r["pods_running"], r["incidents"]) == (True, 1, 2, {"critica": 1, "alta": 0, "media": 2})
    assert k8s_fleet.resumen("otro", None, AHORA) == {"name": "otro", "reporting": False}


@pytest.fixture
def cliente(monkeypatch):
    s = SimpleNamespace(azure=SimpleNamespace(azure_credentials=object(), azure_connected=True))
    app.dependency_overrides[deps.services] = lambda: s
    monkeypatch.setenv("K8S_CLUSTERS", "homelab,sin-agente")
    fotos = {"homelab": foto_homelab(), "sin-agente": None}
    monkeypatch.setattr(k8s_fleet, "leer", lambda cred, nombre: fotos[nombre])
    monkeypatch.setattr(k8s_fleet, "ahora", lambda: AHORA)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_rutas_de_clusteres(cliente):
    lista = cliente.get("/api/k8s/clusters").json()["clusters"]
    assert [(c["name"], c["reporting"]) for c in lista] == [("homelab", True), ("sin-agente", False)]
    assert lista[0]["health"] == 67 and lista[0]["distribution"] == "k3s"

    detalle = cliente.get("/api/k8s/clusters/homelab").json()
    assert [p["name"] for p in detalle["problem_pods"]] == ["web-1"]
    assert detalle["workload_list"][0]["name"] == "web"  # los degradados primero
    assert len(detalle["incident_list"]) == 3

    assert cliente.get("/api/k8s/clusters/sin-agente").status_code == 404
    assert cliente.get("/api/k8s/clusters/desconocido").status_code == 404

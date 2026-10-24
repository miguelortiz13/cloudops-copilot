"""
Kubernetes como proveedor del modelo canónico (docs/plan/08-kubernetes.md).

No habla con ningún clúster: lee la foto que sube el agente de cada uno
(app/services/k8s_fleet.py). Cada clúster es una cuenta
(`kubernetes:cluster/<nombre>`); el clúster, sus nodos y sus cargas son
recursos; las reglas `k8s.*` del catálogo se evalúan sobre las banderas de
seguridad de cada carga.

Un clúster cuya foto tiene más de 24 h queda fuera de la recolección: sin datos
frescos no se dan de baja sus recursos ni se resuelven sus hallazgos.
"""

import os
from datetime import datetime
from typing import Callable, Dict, FrozenSet, List, Optional, Sequence

from app.compliance.catalog import REGLAS
from app.providers.base import (
    Capacidad, CapacidadNoSoportada, Cuenta, Hallazgo, Recurso, ResultadoActividad, ResultadoSeguridad,
)
from app.services import k8s_fleet

VIGENCIA_SEGUNDOS = 24 * 3600
SISTEMA_POR_DEFECTO = "kube-system,kube-public,kube-node-lease"
_REGLA = {t: r.id for t, r in REGLAS.items() if r.proveedor == "kubernetes"}


def account_uid(cluster: str) -> str:
    return f"kubernetes:cluster/{cluster}"


def _imagen_mutable(imagen: Optional[str]) -> bool:
    if not imagen or "@" in imagen:
        return False
    ultima = imagen.rsplit("/", 1)[-1]
    return ":" not in ultima or ultima.endswith(":latest")


class KubernetesProvider:
    nombre = "kubernetes"

    def __init__(self, leer: Callable[[str], Optional[Dict]], clusters: Sequence[str], momento: datetime,
                 excluidos: Optional[Sequence[str]] = None):
        self._leer, self._clusters, self._momento = leer, list(clusters), momento
        self._excluidos = set(excluidos if excluidos is not None else SISTEMA_POR_DEFECTO.split(","))
        self._fotos: Optional[Dict[str, Dict]] = None

    @classmethod
    def desde_entorno(cls, momento: datetime) -> "KubernetesProvider":
        from azure.identity import DefaultAzureCredential

        credenciales = DefaultAzureCredential(managed_identity_client_id=os.getenv("AZURE_MANAGED_IDENTITY_CLIENT_ID") or None)
        excluidos = [n.strip() for n in os.getenv("K8S_EXCLUDED_NAMESPACES", SISTEMA_POR_DEFECTO).split(",") if n.strip()]
        return cls(lambda nombre: k8s_fleet.leer(credenciales, nombre), k8s_fleet.configurados(), momento, excluidos)

    @staticmethod
    def configurado() -> bool:
        return bool(k8s_fleet.configurados() and os.getenv("K8S_SNAPSHOT_ACCOUNT"))

    def capacidades(self) -> FrozenSet[Capacidad]:
        return frozenset({Capacidad.INVENTARIO, Capacidad.SEGURIDAD})

    def fotos(self) -> Dict[str, Dict]:
        """Las fotos de las últimas 24 h, por clúster (se leen una vez por recolección)."""
        if self._fotos is None:
            self._fotos = {}
            for nombre in self._clusters:
                foto = self._leer(nombre)
                edad = k8s_fleet._segundos(foto.get("collected_at"), self._momento) if foto else None
                if edad is not None and edad <= VIGENCIA_SEGUNDOS:
                    self._fotos[nombre] = foto
        return self._fotos

    def cuentas(self) -> List[Cuenta]:
        return [Cuenta(uid=account_uid(n), provider="kubernetes", native_id=n, name=n) for n in self.fotos()]

    def recursos(self, cuentas: Sequence[str]) -> List[Recurso]:
        salida = []
        for nombre, foto in self.fotos().items():
            cuenta = account_uid(nombre)
            if cuenta not in cuentas:
                continue
            salida.append(Recurso(uid=cuenta, provider="kubernetes", account_uid=cuenta, native_id=nombre, name=nombre,
                                  native_type="kubernetes/Cluster", canonical_type="kubernetes.cluster", region=None,
                                  group_name=None, tags={"distribution": foto.get("distribution") or "",
                                                         "version": foto.get("kubernetes_version") or ""}))
            for n in foto.get("nodes", []):
                salida.append(Recurso(uid=f"{cuenta}/node/{n['name']}", provider="kubernetes", account_uid=cuenta,
                                      native_id=n["name"], name=n["name"], native_type="kubernetes/Node",
                                      canonical_type=None, region=None, group_name=None,
                                      tags={"roles": ",".join(n.get("roles", []))}))
            for w in foto.get("workloads", []):
                salida.append(Recurso(uid=self._uid_carga(cuenta, w), provider="kubernetes", account_uid=cuenta,
                                      native_id=f"{w['namespace']}/{w['name']}", name=w["name"],
                                      native_type=f"apps/{w['kind']}", canonical_type=None, region=None,
                                      group_name=w["namespace"]))
        return salida

    @staticmethod
    def _uid_carga(cuenta: str, w: Dict) -> str:
        return f"{cuenta}/ns/{w['namespace']}/{w['kind'].lower()}/{w['name']}"

    def evaluar_reglas(self, cuentas: Sequence[str]) -> ResultadoSeguridad:
        hallazgos: List[Hallazgo] = []
        sin_evidencia = False
        for nombre, foto in self.fotos().items():
            cuenta = account_uid(nombre)
            if cuenta not in cuentas:
                continue
            version = k8s_fleet.soporte(foto.get("kubernetes_version"), self._momento)
            if version["status"] in ("sin_soporte", "por_vencer"):
                hallazgos.append(Hallazgo(
                    rule_id=_REGLA["k8s_version"], resource_uid=cuenta, account_uid=cuenta,
                    severity="alta" if version["status"] == "sin_soporte" else "media",
                    details={"version": foto.get("kubernetes_version"), "end_of_support": version["eol"],
                             "latest_patch": version["latest_patch"]}))
            for w in foto.get("workloads", []):
                if w["namespace"] in self._excluidos:
                    continue
                seg = w.get("security")
                if seg is None:  # agente anterior a 1.2.0: sin banderas no se puede decir que cumple
                    sin_evidencia = True
                    continue
                for tipo, detalle in self._fallas(seg).items():
                    hallazgos.append(Hallazgo(rule_id=_REGLA[tipo], resource_uid=self._uid_carga(cuenta, w),
                                              account_uid=cuenta, severity=REGLAS[tipo].severity_default,
                                              details={"namespace": w["namespace"], "kind": w["kind"], **detalle}))
        return ResultadoSeguridad(hallazgos=hallazgos,
                                  reglas_sin_evidencia=frozenset(_REGLA.values()) if sin_evidencia else frozenset())

    @staticmethod
    def _fallas(seg: Dict) -> Dict[str, Dict]:
        c = seg.get("containers", [])

        def nombres(condicion):
            return [x["name"] for x in c if condicion(x)]

        fallas = {
            "k8s_privileged": nombres(lambda x: x["privileged"]),
            "k8s_escalation": nombres(lambda x: not x["no_escalation"]),
            "k8s_root": nombres(lambda x: not x["non_root"]),
            "k8s_limits": nombres(lambda x: not x["limits"]),
            "k8s_latest": nombres(lambda x: _imagen_mutable(x.get("image"))),
        }
        salida = {t: {"containers": n} for t, n in fallas.items() if n}
        compartidos = [k for k, v in (("hostNetwork", seg.get("host_network")), ("hostPID", seg.get("host_pid")),
                                      ("hostIPC", seg.get("host_ipc"))) if v]
        if compartidos:
            salida["k8s_host_ns"] = {"shared": compartidos}
        if seg.get("host_path"):
            salida["k8s_host_path"] = {}
        return salida

    def recursos_gestionados(self) -> FrozenSet[str]:
        raise CapacidadNoSoportada("Los estados de Terraform no describen cargas de Kubernetes.")

    def creaciones(self, cuentas: Sequence[str]) -> ResultadoActividad:
        raise CapacidadNoSoportada("La foto del agente no dice quién creó cada carga.")

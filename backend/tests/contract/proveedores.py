"""
Proveedores para la batería de contrato.

Cada fábrica arma su proveedor en los escenarios que el contrato necesita
(normal, inventario roto, una regla sin evidencia, sin IaC). La batería
(test_contrato.py) es la misma para todas: agregar una nube es agregar una
fábrica y sus grabaciones.

AzureProvider corre con sus servicios reales (InventoryService, CostService,
SecOpsService) sobre respuestas grabadas de Resource Graph y de la API HTTP de
Cost Management (grabaciones/azure/). Una consulta sin grabar falla: si el
código empieza a pedir algo nuevo a Azure, hay que grabarlo.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from app.providers.base import (
    Capacidad, CostoDiario, Creacion, Cuenta, Hallazgo, Recurso, ResultadoActividad,
)
from app.providers.memoria import ProveedorEnMemoria

GRABACIONES = Path(__file__).parent / "grabaciones" / "azure"


# ---------------------------------------------------------------- Azure grabado

class _Credencial:
    def get_token(self, *scopes):
        return type("Token", (), {"token": "token-de-prueba"})()


class ClienteGrabado:
    """Imita AzureClient: responde Resource Graph desde grabaciones/azure/resource_graph.json."""

    azure_connected = True

    def __init__(self, consultas_que_fallan: Sequence[str] = ()):
        self.rg = json.loads((GRABACIONES / "resource_graph.json").read_text(encoding="utf-8"))
        self.fallan = set(consultas_que_fallan)
        self.azure_credentials = _Credencial()
        self.pedidas: List[str] = []

    def _nombre(self, kql: str) -> str:
        from app.services import governance, kql as consultas

        seguridad = {
            consultas.NSG_ADMIN_EXPUESTO: "nsgs", consultas.STORAGE_BLOBS_PUBLICOS: "storage",
            consultas.KEYVAULT_PUBLICO: "keyvaults", consultas.IPS_PUBLICAS_ACTIVAS: "public_ips",
            consultas.APPS_SIN_HTTPS: "https", consultas.SQL_PUBLICO: "sql", consultas.RECURSOS_FALLIDOS: "failed",
            consultas.DISCOS_SIN_CMK: "discos",
        }
        if kql in seguridad:
            return seguridad[kql]
        if kql == governance.KQL_CREACIONES:
            return "creaciones"
        if kql.startswith("resourcecontainers"):
            return "suscripciones"
        if kql.startswith("resources | extend provisioningState"):
            return "recursos"
        raise AssertionError(f"Consulta de Resource Graph sin grabar (agregarla a {GRABACIONES.name}/): {kql[:120]}")

    def query_azure_resource_graph(self, kql, bypass_cache=False, subscriptions=None, raise_errors=False):
        nombre = self._nombre(kql)
        self.pedidas.append(nombre)
        if nombre in self.fallan:
            if raise_errors:
                raise RuntimeError(f"Resource Graph respondió 503 a '{nombre}'.")
            return []
        filas = self.rg["seguridad"][nombre] if nombre in self.rg["seguridad"] else self.rg[nombre]
        if subscriptions:
            subs = {s.lower() for s in subscriptions}
            filas = [f for f in filas if _suscripcion_de_fila(f) in subs or nombre == "suscripciones"]
        return [dict(f) for f in filas]


def _suscripcion_de_fila(fila: Dict[str, Any]) -> str:
    if fila.get("subscriptionId"):
        return fila["subscriptionId"].lower()
    m = re.match(r"/subscriptions/([^/]+)/", fila.get("id") or "", re.I)
    return m.group(1).lower() if m else ""


class _Respuesta:
    def __init__(self, status: int, body: Any):
        self.status_code, self._body, self.headers = status, body, {}
        self.text = json.dumps(body)

    def json(self):
        return self._body


class CostManagementGrabado:
    """Reemplaza requests.post de CostService con grabaciones/azure/cost_management.json."""

    def __init__(self, fallan_una_vez: Sequence[str] = ()):
        self.paginas = json.loads((GRABACIONES / "cost_management.json").read_text(encoding="utf-8"))
        self.fallan_una_vez = {s.lower() for s in fallan_una_vez}
        self.llamadas: List[str] = []

    def post(self, url, headers=None, json=None, timeout=None):  # noqa: A002 - firma de requests.post
        if url.endswith("/contrato/pagina-2"):
            sub, pagina = "00000000-0000-4000-8000-0000000000a1", 1
        else:
            sub, pagina = re.search(r"/subscriptions/([^/]+)/providers", url).group(1).lower(), 0
        self.llamadas.append(sub)
        if sub in self.fallan_una_vez and pagina == 0:
            self.fallan_una_vez.discard(sub)
            return _Respuesta(500, {"error": {"code": "InternalServerError", "message": "Error transitorio grabado."}})
        grabada = self.paginas[sub][pagina]
        return _Respuesta(grabada["status"], grabada["body"])


class TfStateGrabado:
    def __init__(self, rg: Dict[str, Any]):
        self._datos = rg["terraform"]

    def get_index(self, force: bool = False):
        return {**self._datos, "managed_ids": {i.lower() for i in self._datos["managed_ids"]}}


SUB_A1 = "00000000-0000-4000-8000-0000000000a1"
SUB_A2 = "00000000-0000-4000-8000-0000000000a2"


@dataclass
class FabricaAzure:
    monkeypatch: Any
    tmp_path: Path
    nombre: str = "azure"
    cuenta_con_costos: str = f"azure:sub/{SUB_A1}"
    cuenta_sin_permiso_de_costos: str = f"azure:sub/{SUB_A2}"
    regla_que_puede_fallar: str = "secrets.vault-public-network"
    cliente: Optional[ClienteGrabado] = None
    costos: Optional[CostManagementGrabado] = None

    def _armar(self, consultas_que_fallan=(), con_terraform=True, costos_fallan_una_vez=()):
        from app.core import config
        from app.providers.azure.provider import AzureProvider
        from app.services import cost_service
        from app.services.cost_service import CostService
        from app.services.inventory_service import InventoryService
        from app.services.secops_service import SecOpsService

        self.monkeypatch.setattr(config, "DATA_DIR", self.tmp_path)
        self.monkeypatch.setattr(cost_service.time, "sleep", lambda s: None)
        self.costos = CostManagementGrabado(costos_fallan_una_vez)
        self.monkeypatch.setattr(cost_service.requests, "post", self.costos.post)
        self.cliente = ClienteGrabado(consultas_que_fallan)
        tfstate = TfStateGrabado(self.cliente.rg) if con_terraform else None
        return AzureProvider(InventoryService(self.cliente), CostService(self.cliente, cache_dir=str(self.tmp_path)),
                             SecOpsService(self.cliente), tfstate, espera_reintento=0)

    def normal(self):
        return self._armar()

    def inventario_roto(self):
        return self._armar(consultas_que_fallan=["recursos"])

    def regla_sin_evidencia(self):
        return self._armar(consultas_que_fallan=["keyvaults"])

    def sin_iac(self):
        return self._armar(con_terraform=False)

    def costos_con_falla_transitoria(self):
        return self._armar(costos_fallan_una_vez=[SUB_A1])


# ---------------------------------------------------------------- aws

class _PaginadorGrabado:
    def __init__(self, paginas, falla):
        self._paginas, self._falla = paginas, falla

    def paginate(self, **kw):
        for i, pagina in enumerate(self._paginas):
            # Falla en la segunda página: lo ya leído no debe salir a medias.
            if self._falla and i == 1:
                from botocore.exceptions import ClientError

                raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}}, "ListResources")
            yield pagina


class ClienteAwsGrabado:
    """Doble de boto3: Organizations, Resource Explorer, Athena, Glue y S3 sobre respuestas grabadas."""

    def __init__(self, inventario_roto=False, athena_falla=False, export_vacio=False, s3_falla=False):
        aws = GRABACIONES.parent / "aws"
        self._datos = {**json.loads((aws / "inventario.json").read_text(encoding="utf-8")),
                       **json.loads((aws / "costos.json").read_text(encoding="utf-8")),
                       **json.loads((aws / "seguridad.json").read_text(encoding="utf-8")),
                       **json.loads((aws / "actividad.json").read_text(encoding="utf-8"))}
        self._roto, self._athena_falla, self._export_vacio = inventario_roto, athena_falla, export_vacio
        self._s3_falla = s3_falla
        self._servicio = ""
        self.consultas: List[str] = []
        self._estados = iter(["QUEUED", "RUNNING", "FAILED" if athena_falla else "SUCCEEDED"])

    def __call__(self, servicio: str, **kw):
        self._servicio = servicio
        return self

    def get_paginator(self, operacion: str):
        return _PaginadorGrabado(self._datos[operacion], self._roto and operacion == "list_resources")

    @staticmethod
    def _error(codigo: str, operacion: str):
        from botocore.exceptions import ClientError

        return ClientError({"Error": {"Code": codigo, "Message": codigo}}, operacion)

    # STS, EC2, RDS, IAM y S3 (reglas de seguridad)
    def get_caller_identity(self):
        return {"Account": "111111111111"}

    def assume_role(self, RoleArn, RoleSessionName):
        if ":role/lab-reader" not in RoleArn:
            raise self._error("AccessDenied", "AssumeRole")
        return {"Credentials": {"AccessKeyId": "ASIA", "SecretAccessKey": "s", "SessionToken": "t"}}

    def describe_security_groups(self, GroupIds):
        return {"SecurityGroups": [g for g in self._datos["describe_security_groups"]["SecurityGroups"] if g["GroupId"] in GroupIds]}

    def describe_network_interfaces(self, Filters):
        return self._datos["describe_network_interfaces"]

    def describe_volumes(self, VolumeIds):
        return self._datos["describe_volumes"]

    def describe_addresses(self):
        return self._datos["describe_addresses"]

    def get_account_summary(self):
        return self._datos["get_account_summary"]

    def get_public_access_block(self, **kw):
        if self._s3_falla:
            raise self._error("AccessDenied", "GetPublicAccessBlock")
        if self._servicio == "s3control":  # la cuenta no tiene bloqueo propio
            raise self._error("NoSuchPublicAccessBlockConfiguration", "GetPublicAccessBlock")
        return self._datos["s3_bucket_public_access_block"]

    def get_bucket_policy_status(self, Bucket):
        return self._datos["get_bucket_policy_status"]

    # Athena
    def start_query_execution(self, QueryString, WorkGroup):
        self.consultas.append(QueryString)
        self._estados = iter(["QUEUED", "RUNNING", "FAILED" if self._athena_falla else "SUCCEEDED"])
        return {"QueryExecutionId": "q-1"}

    def get_query_execution(self, QueryExecutionId):
        estado = next(self._estados)
        return {"QueryExecution": {"Status": {"State": estado, "StateChangeReason": "HIVE_BAD_DATA" if estado == "FAILED" else None}}}

    # Glue y S3 (si el export ya entregó)
    def get_table(self, DatabaseName, Name):
        return {"Table": {"StorageDescriptor": {"Location": "s3://costos-lab/focus/lab-focus/data/"}}}

    def list_objects_v2(self, Bucket, Prefix, MaxKeys):
        return {"KeyCount": 0 if self._export_vacio else 1}


@dataclass
class FabricaAws:
    nombre: str = "aws"
    cuenta_con_costos: str = "aws:account/111111111111"
    # El export cubre a toda la organización: no hay cuentas sin permiso de costos.
    cuenta_sin_permiso_de_costos: Optional[str] = None
    regla_que_puede_fallar: str = "aws.storage.public-access-not-blocked"

    def _armar(self, con_terraform=True, **kw):
        from app.providers.aws.provider import AwsProvider

        cliente = ClienteAwsGrabado(**kw)
        # Índice de estados de Terraform (TfStateService.get_index): el bucket está en IaC.
        estados = (lambda: {"available": True, "managed_arns": {"arn:aws:s3:::lab-datos"}}) if con_terraform else None
        return AwsProvider(cliente, "arn:aws:resource-explorer-2:us-east-1:111111111111:view/v/1",
                           costos={"database": "lab_costos", "table": "focus", "workgroup": "lab-costos"},
                           pausa=lambda s: None, rol_miembro="lab-reader", sesion=lambda credenciales: cliente,
                           estados=estados)

    def normal(self):
        return self._armar()

    def inventario_roto(self):
        return self._armar(inventario_roto=True)

    def regla_sin_evidencia(self):
        return self._armar(s3_falla=True)

    def sin_iac(self):
        return self._armar(con_terraform=False)


# ---------------------------------------------------------------- memoria

def _escenario_en_memoria(**kw) -> ProveedorEnMemoria:
    a, b = "memoria:acct/a", "memoria:acct/b"
    hoy = datetime.now(timezone.utc).date()
    return ProveedorEnMemoria(
        lista_cuentas=[Cuenta(a, "memoria", "a", "Cuenta A"), Cuenta(b, "memoria", "b", "Cuenta B", parent="memoria:org/1")],
        lista_recursos=[
            Recurso("memoria:res/a/vault-1", "memoria", a, "vault-1", "vault-1", "vault", "secrets.vault", "region-1", None, {"env": "prod"}),
            Recurso("memoria:res/a/thing", "memoria", a, "thing", "thing", "thing", None, None, None, {}),
            Recurso("memoria:res/b/app", "memoria", b, "app", "app", "app", "compute.app", "region-2", "grupo", {}),
        ],
        filas_costo=[
            CostoDiario(hoy, a, "memoria:res/a/vault-1", "Vault", Decimal("1.5"), Decimal("1.5"), "USD"),
            CostoDiario(hoy, a, "", "Soporte", Decimal("0.1"), Decimal("0.1"), "USD"),
            CostoDiario(hoy, b, "memoria:res/b/app", "App", Decimal("2"), Decimal("2"), "USD"),
        ],
        hallazgos=[
            Hallazgo("secrets.vault-public-network", "memoria:res/a/vault-1", a, "alta", {"name": "vault-1"}),
            Hallazgo("web.https-not-enforced", "memoria:res/b/app", b, "alta", {"name": "app"}),
        ],
        gestionados={"memoria:res/a/vault-1"},
        actividad=ResultadoActividad([Creacion("memoria:res/b/app", "ana@contoso.example", None, True)]),
        cuentas_denegadas_costos={b},
        **kw,
    )


@dataclass
class FabricaMemoria:
    nombre: str = "memoria"
    cuenta_con_costos: str = "memoria:acct/a"
    cuenta_sin_permiso_de_costos: str = "memoria:acct/b"
    regla_que_puede_fallar: str = "secrets.vault-public-network"
    extra: Dict[str, Any] = field(default_factory=dict)

    def normal(self):
        return _escenario_en_memoria()

    def inventario_roto(self):
        return _escenario_en_memoria(inventario_roto=True)

    def regla_sin_evidencia(self):
        return _escenario_en_memoria(reglas_sin_evidencia={self.regla_que_puede_fallar})

    def sin_iac(self):
        return _escenario_en_memoria(soporta=frozenset(set(Capacidad) - {Capacidad.IAC}))


def hoy() -> date:
    return datetime.now(timezone.utc).date()


def uids(items) -> Set[str]:
    return {i.uid for i in items}

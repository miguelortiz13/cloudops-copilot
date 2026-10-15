"""
AwsProvider: el contrato de app/providers/base.py sobre AWS (fase 2).

* Cuentas: las de la organización (`organizations:ListAccounts`). Si la cuenta
  no es la de administración, solo la propia.
* Recursos: la vista de Resource Explorer de la plataforma
  (infra/modules/aws-onboarding), que cubre todas las regiones indexadas.
* Costos: el export FOCUS 1.2 de la organización consultado con Athena (no la
  API de Cost Explorer, que cobra por llamada).

Entra con credenciales temporales de la federación (federacion.py): no hay
llaves de AWS guardadas.
"""

import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Sequence

from app.providers.aws.types import canonical_type
from app.providers.base import (
    Capacidad, Cobertura, CostoDiario, Cuenta, ProveedorError, Recurso, ResultadoActividad, ResultadoCostos,
    ResultadoSeguridad, requiere,
)

PROVEEDOR = "aws"
PREFIJO_CUENTA = "aws:account/"
# Tags con las que se agrupan los recursos (AWS no tiene grupos de recursos).
TAGS_DE_GRUPO = ("Project", "Application")
# Una consulta de Athena sobre el export de una organización pequeña tarda
# segundos; pasado este tiempo se cancela y la cuenta queda sin dato.
ESPERA_ATHENA_SEGUNDOS = 120
ID_DE_CUENTA = re.compile(r"^[0-9]{12}$")


def account_uid(account_id: str) -> str:
    return f"{PREFIJO_CUENTA}{account_id}"


def resource_uid(arn: str) -> str:
    # Los ARN distinguen mayúsculas: se guardan tal cual.
    return f"aws:{arn}"


def cuenta_de(cuenta_uid: str) -> str:
    if not cuenta_uid.startswith(PREFIJO_CUENTA):
        raise ValueError(f"No es una cuenta de AWS: {cuenta_uid}")
    return cuenta_uid[len(PREFIJO_CUENTA):]


def _nombre(arn: str, tags: Dict[str, str]) -> str:
    """La tag Name si existe; si no, el último tramo del ARN (bucket, i-0abc..., rol)."""
    if tags.get("Name"):
        return tags["Name"]
    recurso = arn.split(":", 5)[-1]
    return recurso.rsplit("/", 1)[-1] or recurso


def _tags(propiedades: List[Dict[str, Any]]) -> Dict[str, str]:
    for p in propiedades or []:
        if p.get("Name") == "tags":
            return {str(t["Key"]): str(t.get("Value") or "") for t in p.get("Data") or [] if t.get("Key")}
    return {}


class AwsProvider:
    nombre = PROVEEDOR

    def __init__(self, cliente: Callable[[str], Any], vista_arn: str, identidad: Optional[Dict[str, Any]] = None,
                 costos: Optional[Dict[str, str]] = None, pausa: Callable[[float], None] = time.sleep):
        """
        `cliente(servicio)` devuelve un cliente de boto3 (o un doble en las pruebas).
        `costos`: database, table y workgroup de Athena del export FOCUS; sin
        ellos la capacidad de costos no se declara.
        """
        self._cliente = cliente
        self._vista = vista_arn
        self._costos = costos if costos and all(costos.get(k) for k in ("database", "table", "workgroup")) else None
        self._pausa = pausa
        # Cómo se conecta, para Administración (cuentas conectadas).
        self.identidad = identidad

    @classmethod
    def desde_entorno(cls) -> "AwsProvider":
        """Credenciales federadas con AWS_ROLE_ARN, AWS_ENTRA_AUDIENCE y AWS_INVENTORY_VIEW_ARN."""
        import boto3

        from app.providers.aws.federacion import asumir_rol

        rol, audiencia = os.environ["AWS_ROLE_ARN"], os.environ["AWS_ENTRA_AUDIENCE"]
        region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        c = asumir_rol(rol, audiencia, region)
        sesion = boto3.Session(aws_access_key_id=c.access_key_id, aws_secret_access_key=c.secret_access_key,
                               aws_session_token=c.session_token, region_name=region)
        return cls(sesion.client, os.environ["AWS_INVENTORY_VIEW_ARN"],
                   identidad={"kind": "federacion_oidc", "client_id": None, "role_arn": rol},
                   costos={"database": os.getenv("AWS_COST_DATABASE", ""), "table": os.getenv("AWS_COST_TABLE", ""),
                           "workgroup": os.getenv("AWS_COST_WORKGROUP", "")})

    @staticmethod
    def configurado() -> bool:
        return all(os.getenv(v) for v in ("AWS_ROLE_ARN", "AWS_ENTRA_AUDIENCE", "AWS_INVENTORY_VIEW_ARN"))

    def capacidades(self) -> FrozenSet[Capacidad]:
        return frozenset({Capacidad.INVENTARIO} | ({Capacidad.COSTOS} if self._costos else set()))

    # ------------------------------------------------------------ inventario

    def cuentas(self) -> List[Cuenta]:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            paginas = self._cliente("organizations").get_paginator("list_accounts").paginate()
            return [Cuenta(uid=account_uid(a["Id"]), provider=PROVEEDOR, native_id=a["Id"], name=a.get("Name") or a["Id"])
                    for p in paginas for a in p["Accounts"] if a.get("Status", "ACTIVE") == "ACTIVE"]
        except ClientError as e:
            codigo = e.response.get("Error", {}).get("Code", "")
            if codigo not in ("AccessDeniedException", "AWSOrganizationsNotInUseException"):
                raise ProveedorError(f"Organizations no respondió: {codigo or e}") from None
        except BotoCoreError as e:
            raise ProveedorError(f"Organizations no respondió: {e}") from None
        # Cuenta miembro o sin organización: solo la propia.
        try:
            propia = self._cliente("sts").get_caller_identity()["Account"]
        except (ClientError, BotoCoreError) as e:
            raise ProveedorError(f"STS no respondió: {e}") from None
        return [Cuenta(uid=account_uid(propia), provider=PROVEEDOR, native_id=propia, name=propia)]

    def recursos(self, cuentas: Sequence[str]) -> List[Recurso]:
        from botocore.exceptions import BotoCoreError, ClientError

        ids = {cuenta_de(c) for c in cuentas}
        if not ids:
            return []
        try:
            paginas = self._cliente("resource-explorer-2").get_paginator("list_resources").paginate(ViewArn=self._vista)
            items = [r for p in paginas for r in p.get("Resources") or []]
        except (ClientError, BotoCoreError) as e:
            # Una página que falla deja el inventario incompleto: no se devuelve a medias.
            raise ProveedorError(f"Inventario incompleto: Resource Explorer no respondió ({e}).") from None

        vistos: Dict[str, Recurso] = {}
        for r in items:
            arn, cuenta = r.get("Arn"), r.get("OwningAccountId")
            if not arn or cuenta not in ids:
                continue
            uid = resource_uid(arn)
            if uid in vistos:
                continue
            tags = _tags(r.get("Properties"))
            tipo = (r.get("ResourceType") or "").lower()
            region = r.get("Region")
            vistos[uid] = Recurso(
                uid=uid, provider=PROVEEDOR, account_uid=account_uid(cuenta), native_id=arn, name=_nombre(arn, tags),
                native_type=tipo, canonical_type=canonical_type(tipo),
                region=None if region in (None, "", "global") else region,
                group_name=next((tags[t] for t in TAGS_DE_GRUPO if tags.get(t)), None), tags=tags,
            )
        return list(vistos.values())

    # ------------------------------------------------------------ costos

    def export_entregado(self) -> bool:
        """
        Si el export ya dejó datos. Antes de la primera entrega (hasta 24 h
        después de crearlo) no hay filas, y eso es "sin dato", no gasto cero.
        """
        from botocore.exceptions import BotoCoreError, ClientError

        requiere(self, Capacidad.COSTOS)
        try:
            tabla = self._cliente("glue").get_table(DatabaseName=self._costos["database"], Name=self._costos["table"])
            ubicacion = tabla["Table"]["StorageDescriptor"]["Location"]
            bucket, _, prefijo = ubicacion.removeprefix("s3://").partition("/")
            r = self._cliente("s3").list_objects_v2(Bucket=bucket, Prefix=prefijo, MaxKeys=1)
        except (ClientError, BotoCoreError, KeyError) as e:
            raise ProveedorError(f"No se pudo revisar el export de costos: {e}") from None
        return r.get("KeyCount", 0) > 0

    def _consultar(self, sql: str) -> List[List[str]]:
        athena = self._cliente("athena")
        q = athena.start_query_execution(QueryString=sql, WorkGroup=self._costos["workgroup"])["QueryExecutionId"]
        limite = time.monotonic() + ESPERA_ATHENA_SEGUNDOS
        while True:
            estado = athena.get_query_execution(QueryExecutionId=q)["QueryExecution"]["Status"]
            if estado["State"] == "SUCCEEDED":
                break
            if estado["State"] in ("FAILED", "CANCELLED"):
                raise ProveedorError(f"Athena: {estado.get('StateChangeReason') or estado['State']}")
            if time.monotonic() > limite:
                athena.stop_query_execution(QueryExecutionId=q)
                raise ProveedorError("Athena no terminó a tiempo.")
            self._pausa(1.0)
        filas = []
        for pagina in athena.get_paginator("get_query_results").paginate(QueryExecutionId=q):
            filas += [[c.get("VarCharValue", "") for c in f["Data"]] for f in pagina["ResultSet"]["Rows"]]
        return filas[1:]  # la primera fila son los nombres de columna

    def costos_diarios(self, cuentas: Sequence[str], dias: int) -> ResultadoCostos:
        """Gasto diario por cuenta, recurso y servicio del export FOCUS, consultado con Athena."""
        from botocore.exceptions import BotoCoreError, ClientError

        requiere(self, Capacidad.COSTOS)
        ids = sorted({cuenta_de(c) for c in cuentas})
        if not ids:
            return ResultadoCostos([], Cobertura())
        # Los ids van dentro del SQL: se validan aunque vengan de Organizations.
        if not all(ID_DE_CUENTA.match(i) for i in ids):
            raise ValueError(f"Id de cuenta de AWS inválido: {ids}")
        desde = datetime.now(timezone.utc).date() - timedelta(days=dias)
        sql = (
            "SELECT date(chargeperiodstart), subaccountid, coalesce(resourceid, ''), coalesce(servicename, ''), "
            "sum(billedcost), sum(effectivecost), max(billingcurrency) "
            f'FROM "{self._costos["database"]}"."{self._costos["table"]}" '
            f"WHERE billing_period >= '{desde:%Y-%m}' AND chargeperiodstart >= timestamp '{desde} 00:00:00' "
            f"AND subaccountid IN ({', '.join(repr(i) for i in ids)}) GROUP BY 1, 2, 3, 4"
        )
        try:
            filas = self._consultar(sql)
        except (ProveedorError, ClientError, BotoCoreError) as e:
            print(f"[aws] Costos no disponibles: {e}")
            return ResultadoCostos([], Cobertura(fallidas=list(cuentas)))

        resultado = []
        for dia, cuenta, recurso, servicio, facturado, efectivo, moneda in filas:
            resultado.append(CostoDiario(
                charge_date=date.fromisoformat(dia), account_uid=account_uid(cuenta),
                # Un ARN se cruza con el inventario; un id suelto (i-0abc...) igual se conserva por recurso.
                resource_uid=resource_uid(recurso) if recurso else "", service_name=servicio,
                billed_cost=Decimal(facturado or "0"), effective_cost=Decimal(efectivo or "0"),
                currency=(moneda or "USD").upper(),
            ))
        # El export cubre a toda la organización: una cuenta pedida sin filas no gastó.
        return ResultadoCostos(resultado, Cobertura(cubiertas=list(cuentas)))

    # ------------------------------------------------------------ pendientes (fase 2, pasos 5 a 7)
    # Sin declarar: el contrato pide rechazarlas, no devolver vacío.

    def evaluar_reglas(self, cuentas: Sequence[str]) -> ResultadoSeguridad:
        requiere(self, Capacidad.SEGURIDAD)

    def recursos_gestionados(self) -> FrozenSet[str]:
        requiere(self, Capacidad.IAC)

    def creaciones(self, cuentas: Sequence[str]) -> ResultadoActividad:
        requiere(self, Capacidad.ACTIVIDAD)

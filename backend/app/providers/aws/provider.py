"""
AwsProvider: el contrato de app/providers/base.py sobre AWS (fase 2).

Por ahora solo inventario:

* Cuentas: las de la organización (`organizations:ListAccounts`). Si la cuenta
  no es la de administración, solo la propia.
* Recursos: la vista de Resource Explorer de la plataforma
  (infra/modules/aws-onboarding), que cubre todas las regiones indexadas.

Entra con credenciales temporales de la federación (federacion.py): no hay
llaves de AWS guardadas.
"""

import os
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Sequence

from app.providers.aws.types import canonical_type
from app.providers.base import (
    Capacidad, Cuenta, ProveedorError, Recurso, ResultadoActividad, ResultadoCostos, ResultadoSeguridad, requiere,
)

PROVEEDOR = "aws"
PREFIJO_CUENTA = "aws:account/"
# Tags con las que se agrupan los recursos (AWS no tiene grupos de recursos).
TAGS_DE_GRUPO = ("Project", "Application")


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

    def __init__(self, cliente: Callable[[str], Any], vista_arn: str, identidad: Optional[Dict[str, Any]] = None):
        """`cliente(servicio)` devuelve un cliente de boto3 (o un doble en las pruebas)."""
        self._cliente = cliente
        self._vista = vista_arn
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
                   identidad={"kind": "federacion_oidc", "client_id": None, "role_arn": rol})

    @staticmethod
    def configurado() -> bool:
        return all(os.getenv(v) for v in ("AWS_ROLE_ARN", "AWS_ENTRA_AUDIENCE", "AWS_INVENTORY_VIEW_ARN"))

    def capacidades(self) -> FrozenSet[Capacidad]:
        return frozenset({Capacidad.INVENTARIO})

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

    # ------------------------------------------------------------ pendientes (fase 2, pasos 4 a 7)
    # Sin declarar: el contrato pide rechazarlas, no devolver vacío.

    def costos_diarios(self, cuentas: Sequence[str], dias: int) -> ResultadoCostos:
        requiere(self, Capacidad.COSTOS)

    def evaluar_reglas(self, cuentas: Sequence[str]) -> ResultadoSeguridad:
        requiere(self, Capacidad.SEGURIDAD)

    def recursos_gestionados(self) -> FrozenSet[str]:
        requiere(self, Capacidad.IAC)

    def creaciones(self, cuentas: Sequence[str]) -> ResultadoActividad:
        requiere(self, Capacidad.ACTIVIDAD)

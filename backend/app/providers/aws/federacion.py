"""
Credenciales de AWS sin llaves: la identidad administrada pide a Entra ID un
token para la audiencia de federación y AWS STS lo cambia por credenciales
temporales del rol de lectura (AssumeRoleWithWebIdentity).

Esa llamada a STS no va firmada (el token es la prueba), así que basta la
biblioteca estándar. Infraestructura: infra/terraform/aws.tf.

Prueba de la federación desde Azure (no imprime secretos):
    python -m app.providers.aws.federacion
"""

import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from app.providers.base import ProveedorError

_NS = {"sts": "https://sts.amazonaws.com/doc/2011-06-15/"}
SESION = "cloudops-copilot"


@dataclass(frozen=True)
class CredencialesAws:
    access_key_id: str
    secret_access_key: str
    session_token: str
    expiracion: datetime
    rol_asumido: str  # ARN de la sesión: arn:aws:sts::<cuenta>:assumed-role/<rol>/<sesión>


def _token_de_entra(audiencia: str) -> str:
    from azure.identity import DefaultAzureCredential

    credencial = DefaultAzureCredential(
        managed_identity_client_id=os.getenv("AZURE_MANAGED_IDENTITY_CLIENT_ID") or None)
    return credencial.get_token(f"{audiencia}/.default").token


def _post(url: str, datos: bytes) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, data=datos), timeout=30) as r:
        return r.read()


def _texto(nodo: ET.Element, ruta: str) -> str:
    valor = nodo.findtext(ruta, namespaces=_NS)
    if not valor:
        raise ProveedorError(f"Respuesta de STS sin {ruta.split(':')[-1]}.")
    return valor


def asumir_rol(
    rol_arn: str,
    audiencia: str,
    region: str = "us-east-1",
    token: Optional[Callable[[str], str]] = None,
    post: Callable[[str, bytes], bytes] = _post,
) -> CredencialesAws:
    """Cambia un token de Entra ID por credenciales temporales de `rol_arn`."""
    jwt = (token or _token_de_entra)(audiencia)
    datos = urllib.parse.urlencode({
        "Action": "AssumeRoleWithWebIdentity", "Version": "2011-06-15",
        "RoleArn": rol_arn, "RoleSessionName": SESION, "WebIdentityToken": jwt,
    }).encode()
    try:
        cuerpo = post(f"https://sts.{region}.amazonaws.com/", datos)
    except urllib.error.HTTPError as e:
        # STS explica el rechazo (firma, emisor, audiencia o `sub` que no coinciden).
        try:
            raiz = ET.fromstring(e.read())
            detalle = f"{raiz.findtext('.//sts:Code', namespaces=_NS)}: {raiz.findtext('.//sts:Message', namespaces=_NS)}"
        except ET.ParseError:
            detalle = f"HTTP {e.code}"
        raise ProveedorError(f"AWS STS rechazó la federación: {detalle}") from None
    except urllib.error.URLError as e:
        raise ProveedorError(f"AWS STS no respondió: {e.reason}") from None

    r = ET.fromstring(cuerpo).find(".//sts:AssumeRoleWithWebIdentityResult", _NS)
    if r is None:
        raise ProveedorError("Respuesta de STS sin resultado.")
    return CredencialesAws(
        access_key_id=_texto(r, "sts:Credentials/sts:AccessKeyId"),
        secret_access_key=_texto(r, "sts:Credentials/sts:SecretAccessKey"),
        session_token=_texto(r, "sts:Credentials/sts:SessionToken"),
        expiracion=datetime.fromisoformat(_texto(r, "sts:Credentials/sts:Expiration").replace("Z", "+00:00")),
        rol_asumido=_texto(r, "sts:AssumedRoleUser/sts:Arn"),
    )


def main() -> int:
    rol, audiencia = os.getenv("AWS_ROLE_ARN", ""), os.getenv("AWS_ENTRA_AUDIENCE", "")
    if not rol or not audiencia:
        print("Faltan AWS_ROLE_ARN y AWS_ENTRA_AUDIENCE (infra/terraform/aws.tf).")
        return 2
    try:
        c = asumir_rol(rol, audiencia, os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    except Exception as e:  # la prueba informa cualquier fallo, sin traza
        print(f"FALLÓ: {e}")
        return 1
    print(f"OK: sesión {c.rol_asumido}, vence {c.expiracion.isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

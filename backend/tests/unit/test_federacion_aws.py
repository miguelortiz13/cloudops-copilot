"""Federación con AWS: el token de Entra se cambia en STS por credenciales temporales."""

import io
import urllib.error
import urllib.parse

import pytest

from app.providers.aws.federacion import asumir_rol
from app.providers.base import ProveedorError

ROL = "arn:aws:iam::111111111111:role/cloudops-dev-reader"

OK = b"""<AssumeRoleWithWebIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">
  <AssumeRoleWithWebIdentityResult>
    <Credentials>
      <AccessKeyId>ASIAEJEMPLO</AccessKeyId>
      <SecretAccessKey>secreto</SecretAccessKey>
      <SessionToken>sesion</SessionToken>
      <Expiration>2026-10-14T18:00:00Z</Expiration>
    </Credentials>
    <AssumedRoleUser>
      <Arn>arn:aws:sts::111111111111:assumed-role/cloudops-dev-reader/cloudops-copilot</Arn>
    </AssumedRoleUser>
  </AssumeRoleWithWebIdentityResult>
</AssumeRoleWithWebIdentityResponse>"""

DENEGADO = b"""<ErrorResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">
  <Error><Type>Sender</Type><Code>AccessDenied</Code><Message>Not authorized to perform sts:AssumeRoleWithWebIdentity</Message></Error>
</ErrorResponse>"""


def test_cambia_el_token_de_entra_por_credenciales():
    enviado = {}

    def post(url, datos):
        enviado.update(url=url, **urllib.parse.parse_qs(datos.decode()))
        return OK

    c = asumir_rol(ROL, "aud-123", "us-east-1", token=lambda aud: f"jwt-para-{aud}", post=post)

    assert enviado["url"] == "https://sts.us-east-1.amazonaws.com/"
    assert enviado["Action"] == ["AssumeRoleWithWebIdentity"]
    assert enviado["RoleArn"] == [ROL]
    assert enviado["WebIdentityToken"] == ["jwt-para-aud-123"]
    assert (c.access_key_id, c.secret_access_key, c.session_token) == ("ASIAEJEMPLO", "secreto", "sesion")
    assert c.expiracion.isoformat() == "2026-10-14T18:00:00+00:00"
    assert c.rol_asumido.endswith("assumed-role/cloudops-dev-reader/cloudops-copilot")


def test_rechazo_de_sts_explica_el_motivo():
    def post(url, datos):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, io.BytesIO(DENEGADO))

    with pytest.raises(ProveedorError, match="AccessDenied: Not authorized"):
        asumir_rol(ROL, "aud", token=lambda aud: "jwt", post=post)


def test_respuesta_incompleta_no_entrega_credenciales():
    sin_token = OK.replace(b"<SessionToken>sesion</SessionToken>", b"")
    with pytest.raises(ProveedorError, match="SessionToken"):
        asumir_rol(ROL, "aud", token=lambda aud: "jwt", post=lambda u, d: sin_token)

"""
Validacion del token entrante del Bot Framework.

El webhook de Teams (`/api/teams/webhook`) no puede exigir un token de usuario:
quien lo invoca es el servicio de Bot Framework, no una persona. Por eso esta
fuera del middleware de Entra ID (`services/auth.py`, PUBLIC_PATHS). Sin una
validacion propia, sin embargo, ese endpoint queda abierto: cualquiera que
conozca la URL puede lanzarle preguntas al agente, obtener el inventario de la
organizacion en la respuesta y hacer que el bot escriba en el canal de Teams
—ademas de consumir cuota de Gemini.

Bot Framework firma cada peticion con un JWT en la cabecera `Authorization`.
Este modulo lo valida: firma contra el juego de llaves publicas del emisor,
audiencia igual al Microsoft App Id del bot, expiracion, y —cuando el token lo
trae— que el `serviceUrl` del claim coincida con el de la actividad, que es lo
que impide que una actividad legitima se reenvie apuntando la respuesta a otro
servidor.

Emisores aceptados
------------------
El bot esta registrado como `SingleTenant` (ver `terraform/main.tf`), asi que
los tokens pueden venir de dos sitios segun el canal y la configuracion:

* `https://api.botframework.com` — emisor clasico del servicio de canales.
* `https://login.microsoftonline.com/<tenant>/v2.0` y
  `https://sts.windows.net/<tenant>/` — emisores del tenant, que es lo que usan
  los bots de tipo SingleTenant y User-Assigned MSI.

Se acepta cualquiera de ellos, pero la llave publica se busca en el juego de
llaves del emisor que declara el propio token, nunca en otro.

Configuracion
-------------
    BOT_AUTH_ENABLED=true            (por defecto: true)
    MICROSOFT_APP_ID=<app id>        (si falta, se usa AZURE_CLIENT_ID)
    AZURE_TENANT_ID=<tenant>

A diferencia del middleware de Entra ID, aqui el valor por defecto es *exigir*
el token. Un webhook publico es una puerta abierta a internet, y el coste de
equivocarse por omision es mucho mayor que el de una variable mal puesta: si
falta el App Id con la validacion activa, se rechaza todo y se deja constancia
en el log. Para desarrollo local se puede poner `BOT_AUTH_ENABLED=false`.
"""

import os
import threading
from typing import Any, Dict, Optional

import requests

BOT_AUTH_ENABLED = os.getenv("BOT_AUTH_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)

# El App Id del bot es la audiencia esperada del token. Terraform inyecta el
# mismo valor en AZURE_CLIENT_ID (`microsoft_app_id`), asi que sirve de respaldo.
APP_ID = os.getenv("MICROSOFT_APP_ID") or os.getenv("AZURE_CLIENT_ID", "")
TENANT_ID = os.getenv("AZURE_TENANT_ID", "")

BOTFRAMEWORK_ISSUER = "https://api.botframework.com"
BOTFRAMEWORK_OPENID = (
    "https://login.botframework.com/v1/.well-known/openidconfiguration"
)

# Un cliente de llaves por emisor. PyJWKClient mantiene las llaves en memoria y
# solo vuelve a descargarlas cuando aparece un `kid` desconocido; crearlo por
# peticion significaria una descarga por cada mensaje de Teams.
_jwk_clients: Dict[str, Any] = {}
_jwk_lock = threading.Lock()


class BotAuthError(Exception):
    """El token entrante no es un token valido del Bot Framework."""


def _tenant_issuers() -> Dict[str, str]:
    """Emisores del tenant y su juego de llaves, para bots SingleTenant."""
    if not TENANT_ID:
        return {}
    keys = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"
    return {
        f"https://login.microsoftonline.com/{TENANT_ID}/v2.0": keys,
        f"https://sts.windows.net/{TENANT_ID}/": keys,
    }


def _botframework_jwks_uri() -> str:
    """
    Descubre el `jwks_uri` del servicio de canales.

    La direccion se lee del documento OpenID en vez de fijarla en el codigo
    porque Microsoft la rota; el resultado se guarda en memoria tras la primera
    llamada.
    """
    cached = _jwk_clients.get("__bf_jwks_uri__")
    if cached:
        return cached
    resp = requests.get(BOTFRAMEWORK_OPENID, timeout=10)
    resp.raise_for_status()
    uri = resp.json().get("jwks_uri")
    if not uri:
        raise BotAuthError("El documento OpenID de Bot Framework no trae jwks_uri.")
    _jwk_clients["__bf_jwks_uri__"] = uri
    return uri


def _jwks_uri_for(issuer: str) -> str:
    """Juego de llaves que corresponde al emisor declarado por el token."""
    if issuer == BOTFRAMEWORK_ISSUER:
        return _botframework_jwks_uri()
    uri = _tenant_issuers().get(issuer)
    if not uri:
        raise BotAuthError(f"Emisor no reconocido: {issuer}")
    return uri


def _client_for(jwks_uri: str):
    with _jwk_lock:
        client = _jwk_clients.get(jwks_uri)
        if client is None:
            from jwt import PyJWKClient

            client = PyJWKClient(jwks_uri, cache_keys=True)
            _jwk_clients[jwks_uri] = client
        return client


def validate_bot_token(
    authorization_header: str, service_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Valida el JWT entrante y devuelve sus claims.

    Lanza `BotAuthError` con el motivo si el token falta, esta mal formado, no
    lo firma un emisor conocido, no va dirigido a este bot o ya expiro.
    """
    import jwt  # PyJWT; import diferido, igual que en services/auth.py

    if not APP_ID:
        raise BotAuthError(
            "MICROSOFT_APP_ID/AZURE_CLIENT_ID no esta configurado: no hay "
            "audiencia contra la cual validar el token del bot."
        )

    if not authorization_header.startswith("Bearer "):
        raise BotAuthError("Falta la cabecera Authorization con el token del bot.")

    token = authorization_header[7:].strip()

    # El emisor se lee sin verificar solo para saber donde buscar la llave; la
    # firma se comprueba despues contra ese juego de llaves, y el emisor se
    # vuelve a validar dentro de jwt.decode.
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
    except Exception as exc:
        raise BotAuthError(f"Token ilegible: {exc}") from exc

    issuer = unverified.get("iss", "")
    jwks_uri = _jwks_uri_for(issuer)

    try:
        signing_key = _client_for(jwks_uri).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=APP_ID,
            issuer=issuer,
            options={"verify_exp": True, "verify_aud": True},
        )
    except Exception as exc:
        raise BotAuthError(f"Token invalido: {exc}") from exc

    verificar_service_url(claims, service_url)
    return claims


def verificar_service_url(
    claims: Dict[str, Any], service_url: Optional[str]
) -> None:
    """
    Comprueba que la actividad apunta al mismo servicio que declara el token.

    El claim `serviceurl` ata el token a la direccion a la que el bot va a
    responder. Sin esta comprobacion, un tercero podria reenviar una actividad
    legitima cambiando `serviceUrl` para que la respuesta —con datos del
    inventario— salga hacia un servidor suyo.

    Los tokens que no traen el claim se dejan pasar: no todos los canales lo
    emiten, y rechazarlos dejaria al bot mudo en esos canales.
    """
    claim_service_url = claims.get("serviceurl") or claims.get("serviceUrl")
    if claim_service_url and service_url:
        if claim_service_url.rstrip("/") != service_url.rstrip("/"):
            raise BotAuthError("El serviceUrl de la actividad no coincide con el token.")


def startup_banner() -> None:
    """Deja en el log si el webhook de Teams quedo protegido o abierto."""
    if not BOT_AUTH_ENABLED:
        print(
            "BOT AUTH: DESACTIVADA. /api/teams/webhook acepta actividades de "
            "cualquier origen. Definir BOT_AUTH_ENABLED=true en produccion."
        )
    elif not APP_ID:
        print(
            "BOT AUTH: activa pero falta MICROSOFT_APP_ID/AZURE_CLIENT_ID. "
            "Todas las actividades de Teams seran rechazadas."
        )
    else:
        print(f"BOT AUTH: activa (audiencia {APP_ID[:8]}...).")

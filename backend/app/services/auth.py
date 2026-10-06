"""
Autenticacion con Microsoft Entra ID.

El API expone el inventario completo de Azure de la organizacion —nombres de
recursos, grupos, suscripciones, costos y hallazgos de seguridad— y hasta ahora
respondia a cualquiera que conociera la URL. Este modulo agrega validacion de
token JWT emitido por Entra ID.

Se activa con variables de entorno para que la plataforma pueda seguir
corriendo en local sin friccion:

    AUTH_ENABLED=true
    AZURE_AD_TENANT_ID=<tenant>
    AZURE_AD_API_CLIENT_ID=<application (client) id del App Registration del API>

Con `AUTH_ENABLED` en false (el valor por defecto) el modulo no bloquea nada,
pero deja un aviso en el log de arranque para que la exposicion no pase
inadvertida.

Rutas siempre publicas:

* `/`                     — sonda de disponibilidad.
* `/api/inventory/health` — health check sin secretos.
* `/api/teams/webhook`    — lo invoca el Bot Framework, que trae su propio
                            esquema de autenticacion y no puede presentar un
                            token de usuario.
"""

import os
import threading
from typing import Any, Dict

from fastapi import Request
from fastapi.responses import JSONResponse

AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").strip().lower() in ("1", "true", "yes")
TENANT_ID = os.getenv("AZURE_AD_TENANT_ID") or os.getenv("AZURE_TENANT_ID", "")
API_CLIENT_ID = os.getenv("AZURE_AD_API_CLIENT_ID", "")

# Rutas que nunca exigen token.
PUBLIC_PATHS = {
    "/",
    "/api/inventory/health",
    "/api/teams/webhook",
    "/docs",
    "/openapi.json",
    "/redoc",
}

# El cliente de JWKS se crea una sola vez: mantiene en memoria las llaves
# publicas de Entra ID y las renueva solo cuando aparece un `kid` desconocido.
# Instanciarlo por peticion significaria descargar el juego de llaves en cada
# request.
_jwk_client = None
_jwk_lock = threading.Lock()


def _get_jwk_client():
    global _jwk_client
    with _jwk_lock:
        if _jwk_client is None:
            from jwt import PyJWKClient

            _jwk_client = PyJWKClient(
                f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys",
                cache_keys=True,
            )
        return _jwk_client


def _unauthorized(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": detail},
        headers={"WWW-Authenticate": "Bearer"},
    )


def validate_token(token: str) -> Dict[str, Any]:
    """
    Valida firma, emisor, audiencia y expiracion del token.

    Lanza una excepcion si el token no es valido; devuelve los claims si lo es.
    """
    import jwt  # PyJWT; import diferido para no exigirlo cuando AUTH_ENABLED=false

    signing_key = _get_jwk_client().get_signing_key_from_jwt(token)

    # Entra ID emite tokens v1.0 y v2.0 con emisores distintos; se aceptan ambos
    # porque cual se recibe depende de como quedo configurado el App Registration.
    valid_issuers = [
        f"https://login.microsoftonline.com/{TENANT_ID}/v2.0",
        f"https://sts.windows.net/{TENANT_ID}/",
    ]

    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=[API_CLIENT_ID, f"api://{API_CLIENT_ID}"],
        issuer=valid_issuers,
        options={"verify_exp": True, "verify_aud": True},
    )
    return claims


async def auth_middleware(request: Request, call_next):
    """Middleware que exige un bearer token valido en las rutas protegidas."""
    if not AUTH_ENABLED:
        return await call_next(request)

    path = request.url.path
    # El preflight de CORS no lleva Authorization y debe pasar sin validar.
    if request.method == "OPTIONS" or path in PUBLIC_PATHS:
        return await call_next(request)

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return _unauthorized("Se requiere un token de acceso de Microsoft Entra ID.")

    token = header[7:].strip()
    try:
        claims = validate_token(token)
    except Exception as exc:
        return _unauthorized(f"Token invalido: {exc}")

    # Los claims quedan disponibles para auditoria en los handlers.
    request.state.user = {
        "oid": claims.get("oid"),
        "name": claims.get("name"),
        "upn": claims.get("preferred_username") or claims.get("upn"),
    }
    return await call_next(request)


def startup_banner() -> None:
    """Deja constancia en el log de si el API quedo abierto o protegido."""
    if AUTH_ENABLED:
        if not TENANT_ID or not API_CLIENT_ID:
            print(
                "AUTENTICACION: AUTH_ENABLED=true pero falta AZURE_AD_TENANT_ID o "
                "AZURE_AD_API_CLIENT_ID. Todas las peticiones seran rechazadas."
            )
        else:
            print(f"AUTENTICACION: activa (Entra ID, tenant {TENANT_ID[:8]}...).")
    else:
        print(
            "AUTENTICACION: DESACTIVADA. El API responde sin credenciales a "
            "cualquiera que alcance la URL. Definir AUTH_ENABLED=true para exigir "
            "token de Entra ID."
        )

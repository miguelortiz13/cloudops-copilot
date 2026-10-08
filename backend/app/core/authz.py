"""
Autorizacion por rol (app roles de Entra ID).

La autenticacion (services/auth.py) dice quien es; esto dice que puede hacer.
Los roles son jerarquicos:

| Rol           | App role del API   | Puede                                                  |
|---------------|--------------------|--------------------------------------------------------|
| lector        | CloudOps.Reader    | todo lo que lee                                        |
| operador      | CloudOps.Operator  | + gestionar hallazgos, sincronizar, agente Kubernetes, |
|               |                    |   alertas de prueba a Teams                            |
| administrador | CloudOps.Admin     | + estado de la base, auditoria, reiniciar clientes     |

Un usuario asignado al API sin app role (rol por defecto) es lector: tener
acceso nunca implica poder escribir. Con AUTH_ENABLED=false (desarrollo local)
todo el mundo es administrador; el arranque ya advierte de ese modo.
"""

from dataclasses import dataclass, field
from typing import Dict, List

from fastapi import Depends, HTTPException, Request

from app.services import auth

NIVELES = {"lector": 1, "operador": 2, "administrador": 3}
ROL_DE_APP_ROLE = {
    "CloudOps.Reader": "lector",
    "CloudOps.Operator": "operador",
    "CloudOps.Admin": "administrador",
}


@dataclass
class Usuario:
    nombre: str
    upn: str
    oid: str
    rol: str
    app_roles: List[str] = field(default_factory=list)

    @property
    def actor(self) -> str:
        """Como aparece en historiales y auditoria."""
        return self.upn or self.nombre or self.oid or "desconocido"

    def puede(self, rol: str) -> bool:
        return NIVELES[self.rol] >= NIVELES[rol]

    def a_dict(self) -> Dict:
        return {
            "name": self.nombre, "upn": self.upn, "role": self.rol, "app_roles": self.app_roles,
            "permissions": {r: self.puede(r) for r in NIVELES},
            "auth_enabled": auth.AUTH_ENABLED,
        }


def usuario_actual(request: Request) -> Usuario:
    if not auth.AUTH_ENABLED:
        return Usuario(nombre="Desarrollo local", upn="", oid="", rol="administrador")
    datos = getattr(request.state, "user", None) or {}
    app_roles = list(datos.get("roles") or [])
    roles = [ROL_DE_APP_ROLE[r] for r in app_roles if r in ROL_DE_APP_ROLE]
    rol = max(roles, key=NIVELES.get) if roles else "lector"
    return Usuario(nombre=datos.get("name") or "", upn=datos.get("upn") or "", oid=datos.get("oid") or "",
                   rol=rol, app_roles=app_roles)


def requiere(rol: str):
    """Dependencia que exige al menos `rol`: `dependencies=[requiere("operador")]`."""
    if rol not in NIVELES:
        raise ValueError(rol)

    def verificar(request: Request) -> Usuario:
        usuario = usuario_actual(request)
        if not usuario.puede(rol):
            print(f"[authz] Denegado: {usuario.actor} ({usuario.rol}) -> {request.method} {request.url.path} requiere {rol}")
            raise HTTPException(status_code=403, detail=f"Esta acción requiere el rol {rol}; tu rol es {usuario.rol}.")
        return usuario

    return Depends(verificar)

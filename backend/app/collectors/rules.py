"""
Reglas de seguridad conocidas por la base.

Cada `tipo` del reporte de SecOps es una regla con identificador estable.
Primera version del catalogo: el mapeo a CIS e ISO 27001 es otro entregable
de la fase 1 y se completa en `frameworks`.
"""

from typing import Dict, NamedTuple, Optional


class Regla(NamedTuple):
    id: str
    capability: str
    title: str
    severity_default: str
    remediation: str


REGLAS: Dict[str, Regla] = {
    "nsg": Regla("network.admin-port-open", "security", "Puerto de administración abierto a internet", "alta",
                 "Restringir el origen a rangos corporativos o usar Azure Bastion / Just-In-Time."),
    "storage": Regla("storage.public-blob-access", "security", "Cuenta de almacenamiento con blobs públicos", "alta",
                     "Deshabilitar allowBlobPublicAccess o restringir con reglas de red."),
    "keyvault": Regla("secrets.vault-public-network", "security", "Key Vault alcanzable desde red pública", "alta",
                      "Añadir private endpoint o limitar networkAcls a redes conocidas."),
    "sql": Regla("database.public-network", "security", "SQL Server con acceso público habilitado", "alta",
                 "Deshabilitar publicNetworkAccess y acceder por private endpoint."),
    "https": Regla("web.https-not-enforced", "security", "App Service sin HTTPS obligatorio", "alta",
                   "Activar httpsOnly para impedir tráfico en claro."),
    "disco": Regla("storage.disk-without-cmk", "security", "Disco sin cifrado con llave gestionada por el cliente", "media",
                   "Asociar un Disk Encryption Set si la política de datos lo exige."),
    "failed": Regla("platform.provisioning-failed", "security", "Recurso en estado de aprovisionamiento fallido", "media",
                    "Revisar el despliegue: un recurso en Failed puede quedar a medio configurar."),
}

# Nombre de la consulta de SecOpsService que alimenta cada tipo: si la
# consulta fallo, los hallazgos de esa regla no pueden darse por resueltos.
CONSULTA_DE_TIPO = {"nsg": "nsgs", "storage": "storage", "keyvault": "keyvaults", "sql": "sql",
                    "https": "https", "disco": "discos", "failed": "failed"}


def regla_de(tipo: str) -> Optional[Regla]:
    return REGLAS.get(tipo)

"""
Catalogo de reglas de seguridad y su mapeo a marcos de cumplimiento.

Cada `tipo` del reporte de SecOps es una regla con identificador estable. Cada
regla declara que controles de cada marco evidencia y con que alcance:

* `directa` — la regla comprueba lo mismo que pide el control.
* `parcial` — comprueba una parte o una condicion relacionada; el control
  puede fallar por motivos que la regla no mira.

El catalogo es la fuente de verdad: el recolector lo sincroniza con la tabla
`rules` en cada ejecucion. Los marcos:

* CIS Microsoft Azure Foundations Benchmark 2.0.0, la version que Azure Policy
  publica como iniciativa integrada (los numeros cambian entre versiones).
* ISO/IEC 27001:2022, Anexo A.

Solo se listan los controles que alguna regla o la clasificacion de activos
evidencia: el panel dice que cobertura tiene cada marco en vez de presentar
un porcentaje sobre controles que no se evaluan.
"""

from typing import Dict, List, NamedTuple, Optional, Tuple


class Marco(NamedTuple):
    id: str
    nombre: str
    version: str
    url: str


class Control(NamedTuple):
    marco: str
    id: str
    titulo: str


class Regla(NamedTuple):
    id: str
    capability: str
    title: str
    severity_default: str
    remediation: str
    description: str
    detection: str
    # marco -> ((control, alcance), ...)
    frameworks: Dict[str, Tuple[Tuple[str, str], ...]]
    references: Tuple[str, ...] = ()


CIS = "cis-azure-2.0.0"
ISO = "iso-27001-2022"

MARCOS: Dict[str, Marco] = {
    CIS: Marco(CIS, "CIS Microsoft Azure Foundations Benchmark", "2.0.0",
               "https://www.cisecurity.org/benchmark/azure"),
    ISO: Marco(ISO, "ISO/IEC 27001:2022 · Anexo A", "2022",
               "https://www.iso.org/standard/27001"),
}

_CONTROLES: List[Control] = [
    Control(CIS, "3.7", "Ensure that 'Public access level' is disabled for storage accounts with blob containers"),
    Control(CIS, "4.1.2", "Ensure no Azure SQL Databases allow ingress from 0.0.0.0/0 (ANY IP)"),
    Control(CIS, "6.1", "Ensure that RDP access from the Internet is evaluated and restricted"),
    Control(CIS, "6.2", "Ensure that SSH access from the Internet is evaluated and restricted"),
    Control(CIS, "7.3", "Ensure that 'OS and Data' disks are encrypted with Customer Managed Key (CMK)"),
    Control(CIS, "7.4", "Ensure that 'Unattached disks' are encrypted with 'Customer Managed Key' (CMK)"),
    Control(CIS, "8.7", "Ensure that Private Endpoints are Used for Azure Key Vault"),
    Control(CIS, "9.2", "Ensure Web App Redirects All HTTP traffic to HTTPS in Azure App Service"),
    Control(ISO, "A.5.9", "Inventario de información y otros activos asociados"),
    Control(ISO, "A.5.12", "Clasificación de la información"),
    Control(ISO, "A.5.14", "Transferencia de información"),
    Control(ISO, "A.5.15", "Control de acceso"),
    Control(ISO, "A.8.3", "Restricción del acceso a la información"),
    Control(ISO, "A.8.9", "Gestión de la configuración"),
    Control(ISO, "A.8.12", "Prevención de fuga de datos"),
    Control(ISO, "A.8.20", "Seguridad de las redes"),
    Control(ISO, "A.8.22", "Segregación de redes"),
    Control(ISO, "A.8.24", "Uso de criptografía"),
]
CONTROLES: Dict[Tuple[str, str], Control] = {(c.marco, c.id): c for c in _CONTROLES}

# Controles que evidencia la clasificacion de activos (app/compliance/classification.py),
# no una regla: cumplen cuando todo recurso activo tiene clasificacion.
CONTROLES_DE_CLASIFICACION: Tuple[Tuple[str, str], ...] = ((ISO, "A.5.9"), (ISO, "A.5.12"))

REGLAS: Dict[str, Regla] = {
    "nsg": Regla(
        "network.admin-port-open", "security", "Puerto de administración abierto a internet", "alta",
        "Restringir el origen a rangos corporativos o usar Azure Bastion / Just-In-Time.",
        "Una regla de entrada de un NSG permite RDP (3389) o SSH (22) desde cualquier origen. Es la vía de "
        "entrada más atacada: los escaneos automáticos prueban credenciales en minutos.",
        "Reglas de entrada Allow con origen *, Internet o 0.0.0.0/0 hacia 22 o 3389. Sube a crítica si el NSG "
        "está asociado y hay IPs públicas activas.",
        {CIS: (("6.1", "directa"), ("6.2", "directa")), ISO: (("A.8.20", "directa"), ("A.8.22", "parcial"))},
        ("https://learn.microsoft.com/azure/bastion/bastion-overview",),
    ),
    "storage": Regla(
        "storage.public-blob-access", "security", "Cuenta de almacenamiento con blobs públicos", "alta",
        "Deshabilitar allowBlobPublicAccess o restringir con reglas de red.",
        "La cuenta permite que un contenedor se publique para lectura anónima. Basta con que alguien cambie el "
        "nivel de acceso de un contenedor para exponer su contenido sin credenciales.",
        "allowBlobPublicAccess = true. Sube a crítica si además la cuenta no tiene reglas de red.",
        {CIS: (("3.7", "directa"),), ISO: (("A.5.15", "directa"), ("A.8.3", "directa"), ("A.8.12", "parcial"))},
        ("https://learn.microsoft.com/azure/storage/blobs/anonymous-read-access-prevent",),
    ),
    "keyvault": Regla(
        "secrets.vault-public-network", "security", "Key Vault alcanzable desde red pública", "alta",
        "Añadir private endpoint o limitar networkAcls a redes conocidas.",
        "El almacén de secretos y llaves acepta conexiones desde internet sin private endpoint. Las credenciales "
        "siguen siendo necesarias, pero la superficie expuesta es la de todo internet.",
        "publicNetworkAccess = Enabled y sin private endpoint aprobado. Sube a crítica si no tiene firewall.",
        {CIS: (("8.7", "directa"),), ISO: (("A.8.20", "directa"), ("A.8.24", "parcial"))},
        ("https://learn.microsoft.com/azure/key-vault/general/private-link-service",),
    ),
    "sql": Regla(
        "database.public-network", "security", "SQL Server con acceso público habilitado", "alta",
        "Deshabilitar publicNetworkAccess y acceder por private endpoint.",
        "El servidor lógico acepta conexiones por su endpoint público; el acceso queda en manos de las reglas de "
        "firewall, que suelen abrirse de más.",
        "publicNetworkAccess = Enabled. No revisa el contenido de las reglas de firewall: por eso el control "
        "CIS 4.1.2 (ingreso desde 0.0.0.0/0) se marca como evidencia parcial.",
        {CIS: (("4.1.2", "parcial"),), ISO: (("A.8.20", "directa"), ("A.8.3", "parcial"))},
        ("https://learn.microsoft.com/azure/azure-sql/database/connectivity-settings",),
    ),
    "https": Regla(
        "web.https-not-enforced", "security", "App Service sin HTTPS obligatorio", "alta",
        "Activar httpsOnly para impedir tráfico en claro.",
        "La aplicación responde por HTTP sin redirigir a HTTPS: sesiones y datos pueden viajar en claro.",
        "httpsOnly = false en sitios de App Service y Functions.",
        {CIS: (("9.2", "directa"),), ISO: (("A.5.14", "directa"), ("A.8.24", "parcial"))},
        ("https://learn.microsoft.com/azure/app-service/configure-ssl-bindings#enforce-https",),
    ),
    "disco": Regla(
        "storage.disk-without-cmk", "security", "Disco sin cifrado con llave gestionada por el cliente", "media",
        "Asociar un Disk Encryption Set si la política de datos lo exige.",
        "El disco está cifrado con la llave de la plataforma, no con una llave propia. Es un requisito de "
        "endurecimiento (nivel 2 de CIS), no una exposición: aplica cuando la política de datos lo exige.",
        "Discos administrados sin diskEncryptionSetId, conectados o no.",
        {CIS: (("7.3", "directa"), ("7.4", "directa")), ISO: (("A.8.24", "directa"),)},
        ("https://learn.microsoft.com/azure/virtual-machines/disk-encryption",),
    ),
    "failed": Regla(
        "platform.provisioning-failed", "security", "Recurso en estado de aprovisionamiento fallido", "media",
        "Revisar el despliegue: un recurso en Failed puede quedar a medio configurar.",
        "Un despliegue falló a medias: el recurso puede existir sin la configuración de seguridad que el resto "
        "del despliegue debía aplicar.",
        "provisioningState = Failed en cualquier tipo de recurso.",
        {ISO: (("A.8.9", "directa"),)},
    ),
}

# Nombre de la consulta de SecOpsService que alimenta cada tipo: si la
# consulta fallo, los hallazgos de esa regla no pueden darse por resueltos.
CONSULTA_DE_TIPO = {"nsg": "nsgs", "storage": "storage", "keyvault": "keyvaults", "sql": "sql",
                    "https": "https", "disco": "discos", "failed": "failed"}

POR_ID: Dict[str, Regla] = {r.id: r for r in REGLAS.values()}


def regla_de(tipo: str) -> Optional[Regla]:
    return REGLAS.get(tipo)


def frameworks_json(regla: Regla) -> Dict[str, List[Dict[str, str]]]:
    """Forma que se guarda en `rules.frameworks`."""
    return {marco: [{"control": c, "match": alcance} for c, alcance in controles]
            for marco, controles in regla.frameworks.items()}


def validar() -> List[str]:
    """Errores de coherencia del catalogo (lo ejecutan las pruebas)."""
    errores = []
    ids = [r.id for r in REGLAS.values()]
    if len(ids) != len(set(ids)):
        errores.append("ids de regla repetidos")
    if set(REGLAS) != set(CONSULTA_DE_TIPO):
        errores.append("cada tipo necesita su consulta")
    for r in REGLAS.values():
        for marco, controles in r.frameworks.items():
            if marco not in MARCOS:
                errores.append(f"{r.id}: marco desconocido {marco}")
            for control, alcance in controles:
                if (marco, control) not in CONTROLES:
                    errores.append(f"{r.id}: control desconocido {marco} {control}")
                if alcance not in ("directa", "parcial"):
                    errores.append(f"{r.id}: alcance invalido {alcance}")
    usados = {(m, c) for r in REGLAS.values() for m, cs in r.frameworks.items() for c, _ in cs}
    sobrantes = set(CONTROLES) - usados - set(CONTROLES_DE_CLASIFICACION)
    if sobrantes:
        errores.append(f"controles sin evidencia: {sorted(sobrantes)}")
    return errores

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
* CIS Amazon Web Services Foundations Benchmark 3.0.0, la version de los
  controles de Security Hub (sin activar Security Hub: las reglas las evalua
  la plataforma con llamadas de lectura).

* CIS Kubernetes Benchmark 1.9.0, sección 5.2 (políticas de pods): la evalúa
  la plataforma sobre la foto que envía el agente de cada clúster.

Cada regla pertenece a un proveedor: la evalua su recolector de hallazgos
(`findings` en Azure, `findings_aws` en AWS, `findings_kubernetes` en los
clústeres) y solo cuenta para los controles de su marco y de ISO.
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
    proveedor: str = "azure"


CIS = "cis-azure-2.0.0"
CIS_AWS = "cis-aws-3.0.0"
CIS_K8S = "cis-kubernetes-1.9.0"
ISO = "iso-27001-2022"

# Recolector que evalua las reglas de cada proveedor (app/collectors/run.py).
RECOLECTOR_DE_HALLAZGOS = {"azure": "findings", "aws": "findings_aws", "kubernetes": "findings_kubernetes"}

MARCOS: Dict[str, Marco] = {
    CIS: Marco(CIS, "CIS Microsoft Azure Foundations Benchmark", "2.0.0",
               "https://www.cisecurity.org/benchmark/azure"),
    CIS_AWS: Marco(CIS_AWS, "CIS Amazon Web Services Foundations Benchmark", "3.0.0",
                   "https://www.cisecurity.org/benchmark/amazon_web_services"),
    CIS_K8S: Marco(CIS_K8S, "CIS Kubernetes Benchmark", "1.9.0",
                   "https://www.cisecurity.org/benchmark/kubernetes"),
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
    Control(CIS_AWS, "1.5", "Ensure MFA is enabled for the 'root' user account"),
    Control(CIS_AWS, "2.1.4", "Ensure that S3 is configured with 'Block Public Access' enabled"),
    Control(CIS_AWS, "2.2.1", "Ensure EBS volume encryption is enabled in all regions"),
    Control(CIS_AWS, "2.3.3", "Ensure that public access is not given to RDS Instance"),
    Control(CIS_AWS, "5.2", "Ensure no security groups allow ingress from 0.0.0.0/0 to remote server administration ports"),
    Control(CIS_AWS, "5.3", "Ensure no security groups allow ingress from ::/0 to remote server administration ports"),
    Control(CIS_K8S, "5.2.2", "Minimize the admission of privileged containers"),
    Control(CIS_K8S, "5.2.3", "Minimize the admission of containers wishing to share the host process ID namespace"),
    Control(CIS_K8S, "5.2.4", "Minimize the admission of containers wishing to share the host IPC namespace"),
    Control(CIS_K8S, "5.2.5", "Minimize the admission of containers wishing to share the host network namespace"),
    Control(CIS_K8S, "5.2.6", "Minimize the admission of containers with allowPrivilegeEscalation"),
    Control(CIS_K8S, "5.2.7", "Minimize the admission of root containers"),
    Control(CIS_K8S, "5.2.12", "Minimize the admission of HostPath volumes"),
    Control(ISO, "A.5.9", "Inventario de información y otros activos asociados"),
    Control(ISO, "A.5.12", "Clasificación de la información"),
    Control(ISO, "A.5.14", "Transferencia de información"),
    Control(ISO, "A.5.15", "Control de acceso"),
    Control(ISO, "A.8.2", "Derechos de acceso privilegiado"),
    Control(ISO, "A.8.3", "Restricción del acceso a la información"),
    Control(ISO, "A.8.6", "Gestión de la capacidad"),
    Control(ISO, "A.8.8", "Gestión de vulnerabilidades técnicas"),
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
    # ---------------------------------------------------------------- AWS
    "aws_sg": Regla(
        "aws.network.admin-port-open", "security", "Security group con puerto de administración abierto a internet", "alta",
        "Restringir el origen a rangos corporativos o usar Session Manager en lugar de SSH/RDP.",
        "Una regla de entrada de un security group permite SSH (22) o RDP (3389) desde cualquier dirección. "
        "Es la vía de entrada más atacada: los escaneos automáticos prueban credenciales en minutos.",
        "Reglas de entrada con origen 0.0.0.0/0 o ::/0 cuyo rango de puertos incluye 22 o 3389 (o todos los "
        "puertos). Sube a crítica si el grupo está asociado a alguna interfaz de red.",
        {CIS_AWS: (("5.2", "directa"), ("5.3", "directa")), ISO: (("A.8.20", "directa"), ("A.8.22", "parcial"))},
        ("https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager.html",), "aws",
    ),
    "aws_s3": Regla(
        "aws.storage.public-access-not-blocked", "security", "Bucket S3 sin bloqueo de acceso público", "alta",
        "Activar las cuatro opciones de Block Public Access en la cuenta (cubre todos los buckets) o en el bucket.",
        "Ni la cuenta ni el bucket bloquean el acceso público: basta una política o una ACL para exponer su "
        "contenido sin credenciales.",
        "Block Public Access incompleto en la cuenta y en el bucket. Sube a crítica si la política del bucket "
        "ya lo hace público.",
        {CIS_AWS: (("2.1.4", "directa"),), ISO: (("A.5.15", "directa"), ("A.8.3", "directa"), ("A.8.12", "parcial"))},
        ("https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html",), "aws",
    ),
    "aws_rds": Regla(
        "aws.database.public-network", "security", "Instancia RDS accesible públicamente", "alta",
        "Desactivar PubliclyAccessible y conectarse desde la VPC.",
        "La instancia tiene una dirección pública y su acceso queda en manos de los security groups, que suelen "
        "abrirse de más.",
        "PubliclyAccessible = true.",
        {CIS_AWS: (("2.3.3", "directa"),), ISO: (("A.8.20", "directa"), ("A.8.3", "parcial"))},
        ("https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_VPC.WorkingWithRDSInstanceinaVPC.html",), "aws",
    ),
    "aws_ebs": Regla(
        "aws.storage.disk-unencrypted", "security", "Volumen EBS sin cifrar", "media",
        "Activar el cifrado por defecto de EBS en la región y migrar el volumen a uno cifrado (snapshot cifrada).",
        "El volumen guarda sus datos sin cifrar. El control CIS pide el cifrado por defecto en la región; la regla "
        "mira cada volumen, por eso la evidencia es parcial.",
        "Volúmenes con Encrypted = false.",
        {CIS_AWS: (("2.2.1", "parcial"),), ISO: (("A.8.24", "directa"),)},
        ("https://docs.aws.amazon.com/ebs/latest/userguide/encryption-by-default.html",), "aws",
    ),
    "aws_root": Regla(
        "aws.identity.root-without-mfa", "security", "Usuario root sin MFA", "critica",
        "Activar MFA (llave física o passkey) para el usuario root y no usarlo en el día a día.",
        "El usuario root tiene acceso total a la cuenta y no se puede restringir con políticas: sin MFA, una "
        "contraseña filtrada entrega la cuenta entera.",
        "AccountMFAEnabled = 0 en el resumen de IAM de la cuenta.",
        {CIS_AWS: (("1.5", "directa"),), ISO: (("A.5.15", "parcial"),)},
        ("https://docs.aws.amazon.com/IAM/latest/UserGuide/enable-virt-mfa-for-root.html",), "aws",
    ),
    # Recursos sin uso: cobran sin servir a nada. No evidencian controles.
    "aws_ebs_libre": Regla(
        "aws.cost.unattached-volume", "cost", "Volumen EBS sin adjuntar", "media",
        "Tomar una snapshot si los datos importan y borrar el volumen.",
        "El volumen no está conectado a ninguna instancia y se cobra por GB al mes igual que si lo estuviera.",
        "Volúmenes en estado available.",
        {}, ("https://docs.aws.amazon.com/ebs/latest/userguide/ebs-deleting-volume.html",), "aws",
    ),
    "aws_eip_libre": Regla(
        "aws.cost.unassociated-elastic-ip", "cost", "IP elástica sin asociar", "media",
        "Liberar la dirección si no se va a usar.",
        "AWS cobra cada dirección IPv4 pública por hora, esté asociada o no; una sin asociar es gasto sin uso.",
        "Direcciones elásticas sin AssociationId.",
        {}, ("https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/elastic-ip-addresses-eip.html",), "aws",
    ),
    # ---------------------------------------------------------------- Kubernetes (cargas de cada clúster)
    "k8s_privileged": Regla(
        "k8s.workload.privileged", "security", "Contenedor privilegiado", "alta",
        "Quitar privileged: true; si necesita una capacidad concreta, agregar solo esa en capabilities.add.",
        "Un contenedor privilegiado tiene acceso a todos los dispositivos del nodo y casi los mismos permisos que "
        "un proceso root en él: quien lo comprometa controla el nodo.",
        "securityContext.privileged = true en algún contenedor de la plantilla de pods.",
        {CIS_K8S: (("5.2.2", "directa"),), ISO: (("A.8.2", "directa"), ("A.8.9", "parcial"))},
        ("https://kubernetes.io/docs/concepts/security/pod-security-standards/",), "kubernetes",
    ),
    "k8s_host_ns": Regla(
        "k8s.workload.host-namespaces", "security", "Carga que comparte la red, los procesos o el IPC del nodo", "alta",
        "Quitar hostNetwork, hostPID y hostIPC salvo en agentes de nodo que lo necesiten (y aceptar el riesgo ahí).",
        "Compartir los namespaces del nodo deja ver y alcanzar sus procesos, su memoria compartida o su red, "
        "incluidos servicios que solo escuchan en localhost.",
        "hostNetwork, hostPID o hostIPC = true en la plantilla de pods.",
        {CIS_K8S: (("5.2.3", "directa"), ("5.2.4", "directa"), ("5.2.5", "directa")), ISO: (("A.8.22", "parcial"),)},
        ("https://kubernetes.io/docs/concepts/security/pod-security-standards/",), "kubernetes",
    ),
    "k8s_host_path": Regla(
        "k8s.workload.host-path", "security", "Carga que monta rutas del nodo (hostPath)", "media",
        "Usar volúmenes persistentes o emptyDir; si la ruta es imprescindible, montarla de solo lectura.",
        "Un volumen hostPath expone archivos del nodo al contenedor: según la ruta, credenciales del kubelet, el "
        "socket del runtime o la configuración del sistema.",
        "Algún volumen hostPath en la plantilla de pods.",
        {CIS_K8S: (("5.2.12", "directa"),), ISO: (("A.8.3", "parcial"),)},
        ("https://kubernetes.io/docs/concepts/storage/volumes/#hostpath",), "kubernetes",
    ),
    "k8s_escalation": Regla(
        "k8s.workload.privilege-escalation", "security", "Contenedor que puede escalar privilegios", "media",
        "Agregar securityContext.allowPrivilegeEscalation: false a cada contenedor.",
        "Sin allowPrivilegeEscalation: false, un proceso del contenedor puede ganar más privilegios que su padre "
        "(binarios setuid, por ejemplo). Kubernetes lo permite por defecto.",
        "allowPrivilegeEscalation distinto de false en algún contenedor.",
        {CIS_K8S: (("5.2.6", "directa"),), ISO: (("A.8.2", "parcial"),)},
        ("https://kubernetes.io/docs/tasks/configure-pod-container/security-context/",), "kubernetes",
    ),
    "k8s_root": Regla(
        "k8s.workload.run-as-root", "security", "Contenedor que puede correr como root", "media",
        "Definir runAsNonRoot: true (o un runAsUser distinto de 0) en el pod o el contenedor.",
        "Sin runAsNonRoot ni un usuario distinto de 0, el contenedor corre como root si su imagen lo hace: una "
        "fuga del contenedor empieza con más permisos.",
        "Ni runAsNonRoot = true ni runAsUser distinto de 0, en el contenedor o en el pod.",
        {CIS_K8S: (("5.2.7", "directa"),), ISO: (("A.8.2", "parcial"),)},
        ("https://kubernetes.io/docs/tasks/configure-pod-container/security-context/",), "kubernetes",
    ),
    "k8s_limits": Regla(
        "k8s.workload.no-resource-limits", "security", "Contenedor sin límites de recursos", "media",
        "Definir resources.limits (memoria al menos) en cada contenedor, o un LimitRange en el namespace.",
        "Sin límites, un contenedor con una fuga de memoria o un pico de CPU puede dejar sin recursos al resto "
        "de las cargas del nodo.",
        "Algún contenedor sin resources.limits.",
        {ISO: (("A.8.6", "directa"),)},
        ("https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/",), "kubernetes",
    ),
    "k8s_latest": Regla(
        "k8s.workload.mutable-image-tag", "security", "Imagen con etiqueta latest o sin etiqueta", "media",
        "Fijar una versión (o mejor, el digest @sha256) en la imagen.",
        "Con latest o sin etiqueta, cada reinicio puede traer una imagen distinta: no se sabe qué versión corre y "
        "un cambio no revisado entra solo.",
        "Imagen sin etiqueta o con :latest, salvo que use un digest.",
        {ISO: (("A.8.9", "parcial"),)},
        ("https://kubernetes.io/docs/concepts/containers/images/#image-names",), "kubernetes",
    ),
    "k8s_version": Regla(
        "k8s.cluster.unsupported-version", "security", "Clúster con una versión de Kubernetes sin soporte", "alta",
        "Actualizar a una versión menor con soporte (de a una versión por vez); en AKS o EKS, con su asistente de "
        "actualización.",
        "Una versión fuera de soporte no recibe parches de seguridad: las vulnerabilidades que se publiquen después "
        "quedan abiertas para siempre.",
        "Versión menor del API server con fin de soporte vencido según el calendario oficial de Kubernetes (alta) o "
        "que vence en menos de 90 días (media). AKS y EKS suelen dar soporte por más tiempo.",
        {ISO: (("A.8.8", "directa"),)},
        ("https://kubernetes.io/releases/",), "kubernetes",
    ),
}

# Nombre de la consulta de SecOpsService que alimenta cada tipo: si la
# consulta fallo, los hallazgos de esa regla no pueden darse por resueltos.
CONSULTA_DE_TIPO = {"nsg": "nsgs", "storage": "storage", "keyvault": "keyvaults", "sql": "sql",
                    "https": "https", "disco": "discos", "failed": "failed",
                    # AWS: llamada que evalua cada regla (app/providers/aws/seguridad.py).
                    "aws_sg": "security_groups", "aws_s3": "s3", "aws_rds": "rds", "aws_ebs": "ebs", "aws_root": "iam",
                    "aws_ebs_libre": "ebs", "aws_eip_libre": "eips",
                    # Kubernetes: todas salen de la foto del agente (app/providers/kubernetes).
                    "k8s_privileged": "foto", "k8s_host_ns": "foto", "k8s_host_path": "foto", "k8s_escalation": "foto",
                    "k8s_root": "foto", "k8s_limits": "foto", "k8s_latest": "foto", "k8s_version": "foto"}

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
        if r.proveedor not in RECOLECTOR_DE_HALLAZGOS:
            errores.append(f"{r.id}: proveedor desconocido {r.proveedor}")
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

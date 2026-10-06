"""
Catalogo unico de consultas de dominio contra Azure Resource Graph.

Cada regla de la plataforma —que un disco esta huerfano, que una cuenta de
almacenamiento esta expuesta, que un Key Vault es alcanzable— tenia hasta ahora
dos definiciones: una en los servicios que alimentan el panel y otra escrita a
mano dentro de `agent.ask()` para el chat. Las dos versiones divergieron, y la
divergencia era visible para el usuario:

* SecOps corrigio la consulta de almacenamiento para exigir
  `allowBlobPublicAccess == true`. Medido en produccion, eso reduce el hallazgo
  de 354 cuentas (el 96% del inventario, ruido con formato de alerta) a las 112
  que de verdad permiten acceso publico. El chat seguia usando la condicion
  vieja, con `isnull(publicNetworkAccess)` incluido.
* Lo mismo con los Key Vaults: el panel filtra los realmente alcanzables; la
  consulta del chat no tenia clausula `where` y devolvia los 85 del tenant.

El resultado era que el panel y el agente daban cifras distintas del mismo
tenant, y no habia forma de saber cual creer. Este modulo deja una sola
definicion por regla; quien quiera cambiar un umbral lo cambia aqui y el cambio
llega al panel, al chat y a los reportes a la vez.

Convenciones
------------
* Toda consulta proyecta `id` y `subscriptionId`. `id` es la clave para cruzar
  un recurso con su costo en Cost Management, y `subscriptionId` es lo que
  permite decidir por recurso si su cifra de costo es real o estimada, dado que
  el Service Principal solo tiene permisos de costo sobre parte del tenant.
* Las consultas con `limit` se exponen como funciones, porque el limite depende
  de quien consume: el panel muestra tablas y el prompt del agente tiene un
  presupuesto de tokens mucho mas ajustado.
* Todo lo de aqui usa unicamente la tabla `resources`, que el rol `Reader`
  cubre en todo el tenant. Ninguna consulta requiere Defender for Cloud ni
  `Security Reader`.
"""

# ---------------------------------------------------------------------------
# Desperdicio (FinOps)
# ---------------------------------------------------------------------------

DISCOS_HUERFANOS = (
    "resources | where type =~ 'microsoft.compute/disks' "
    "and properties.diskState =~ 'Unattached' "
    "| project id, name, resourceGroup, subscriptionId, "
    "sizeGB = toint(properties.diskSizeGB), location, sku = sku.name"
)

# Una direccion sin `ipConfiguration` no esta asociada a nada y factura igual.
IPS_SIN_ASOCIAR = (
    "resources | where type =~ 'microsoft.network/publicipaddresses' "
    "and isnull(properties.ipConfiguration) "
    "| project id, name, resourceGroup, subscriptionId, "
    "ipAddress = properties.ipAddress, location, sku = sku.name"
)

# Una NIC huerfana no factura por si sola, pero retiene IPs privadas del espacio
# de red y suele ser rastro de una VM borrada a medias.
NICS_HUERFANAS = (
    "resources | where type =~ 'microsoft.network/networkinterfaces' "
    "and isnull(properties.virtualMachine) "
    "| project id, name, resourceGroup, subscriptionId, location"
)

# El plan es lo que se factura; las apps que corren encima no. Un plan sin
# sitios es gasto puro.
APP_PLANS_VACIOS = (
    "resources | where type =~ 'microsoft.web/serverfarms' "
    "| project id, name, resourceGroup, subscriptionId, location, sku = sku.name, "
    "numberOfSites = toint(properties.numberOfSites) "
    "| where numberOfSites == 0 or isnull(numberOfSites)"
)

SNAPSHOTS = (
    "resources | where type =~ 'microsoft.compute/snapshots' "
    "| project id, name, resourceGroup, subscriptionId, location, "
    "sizeGB = toint(properties.diskSizeGB), "
    "timeCreated = todatetime(properties.timeCreated)"
)

RECURSOS_POR_RG = (
    "resources | summarize count() by resourceGroup | order by count_ desc | limit 20"
)


def recursos_sin_tags(limite: int = 25) -> str:
    """Recursos sin ningun tag: ni cost allocation, ni responsable, ni ambiente."""
    return (
        "resources | where isnull(tags) or array_length(bag_keys(tags)) == 0 "
        "| project id, name, type, resourceGroup, subscriptionId, location "
        f"| limit {int(limite)}"
    )


# ---------------------------------------------------------------------------
# Seguridad (SecOps)
# ---------------------------------------------------------------------------

# Reglas de entrada desde internet hacia puertos de administracion. Verificada
# contra produccion: las 43 NSGs que marca estan todas asociadas a una interfaz
# o a una subred, es decir, ninguna es un falso positivo. `asociado` distingue
# la regla teoricamente abierta de la realmente alcanzable.
NSG_ADMIN_EXPUESTO = (
    "resources | where type =~ 'microsoft.network/networksecuritygroups' "
    "| mv-expand rules=properties.securityRules "
    "| where rules.properties.direction =~ 'Inbound' and rules.properties.access =~ 'Allow' "
    "and (rules.properties.destinationPortRange in ('22','3389','*') "
    "  or rules.properties.destinationPortRanges has '22' "
    "  or rules.properties.destinationPortRanges has '3389') "
    "and (rules.properties.sourceAddressPrefix in ('*','0.0.0.0/0','Internet') "
    "  or rules.properties.sourceAddressPrefixes has '*' "
    "  or rules.properties.sourceAddressPrefixes has 'Internet') "
    "| extend asociado = array_length(todynamic(properties.networkInterfaces)) > 0 "
    "  or array_length(todynamic(properties.subnets)) > 0 "
    "| project id, name, resourceGroup, subscriptionId, "
    "  port = tostring(rules.properties.destinationPortRange), "
    "  source = tostring(rules.properties.sourceAddressPrefix), "
    "  ruleName = tostring(rules.name), asociado"
)

# Solo cuentas que permiten explicitamente acceso publico a blobs. Incluir
# `isnull(publicNetworkAccess)` —como hacia la version del chat— marcaba el 96%
# del inventario, porque ese campo viene nulo por defecto. `sinFirewall` es lo
# que convierte la configuracion en exposicion real.
STORAGE_BLOBS_PUBLICOS = (
    "resources | where type =~ 'microsoft.storage/storageaccounts' "
    "| where properties.allowBlobPublicAccess == true "
    "| extend sinFirewall = isnull(properties.networkAcls) "
    "  or tostring(properties.networkAcls.defaultAction) =~ 'Allow' "
    "| project id, name, resourceGroup, location, subscriptionId, "
    "  kind, sinFirewall, "
    "  publicNetworkAccess = tostring(properties.publicNetworkAccess)"
)

# Vaults realmente alcanzables: acceso publico habilitado y sin private
# endpoint. Sin el `where`, se reportaba el inventario completo de vaults.
KEYVAULT_PUBLICO = (
    "resources | where type =~ 'microsoft.keyvault/vaults' "
    "| where tostring(properties.publicNetworkAccess) =~ 'Enabled' "
    "| extend sinPrivateEndpoint = "
    "  array_length(todynamic(properties.privateEndpointConnections)) == 0 "
    "  or isnull(properties.privateEndpointConnections) "
    "| extend sinFirewall = isnull(properties.networkAcls) "
    "  or tostring(properties.networkAcls.defaultAction) =~ 'Allow' "
    "| where sinPrivateEndpoint "
    "| project id, name, resourceGroup, location, subscriptionId, "
    "  sinPrivateEndpoint, sinFirewall"
)

# Superficie de ataque real: direcciones publicas efectivamente asociadas a un
# recurso. Las libres son un asunto de costo (ver IPS_SIN_ASOCIAR), no de
# seguridad.
IPS_PUBLICAS_ACTIVAS = (
    "resources | where type =~ 'microsoft.network/publicipaddresses' "
    "| where isnotnull(properties.ipConfiguration) "
    "| project id, name, resourceGroup, subscriptionId, "
    "  ipAddress = tostring(properties.ipAddress), location, "
    "  sku = tostring(sku.name)"
)

APPS_SIN_HTTPS = (
    "resources | where type =~ 'microsoft.web/sites' "
    "| where properties.httpsOnly == false "
    "| project id, name, resourceGroup, subscriptionId, location, "
    "  kind, defaultHostName = tostring(properties.defaultHostName)"
)

SQL_PUBLICO = (
    "resources | where type =~ 'microsoft.sql/servers' "
    "| where tostring(properties.publicNetworkAccess) =~ 'Enabled' "
    "| project id, name, resourceGroup, subscriptionId, location, "
    "  version = tostring(properties.version), "
    "  admin = tostring(properties.administratorLogin)"
)

# Un recurso en Failed puede haber quedado a medio configurar: es tanto un
# asunto de salud operativa como de seguridad.
RECURSOS_FALLIDOS = (
    "resources | where properties.provisioningState =~ 'Failed' "
    "| project id, name, type, resourceGroup, subscriptionId, location"
)

DISCOS_SIN_CMK = (
    "resources | where type =~ 'microsoft.compute/disks' "
    "| where isnull(properties.encryption.diskEncryptionSetId) "
    "| project id, name, resourceGroup, subscriptionId, location, "
    "  sizeGB = toint(properties.diskSizeGB)"
)


# ---------------------------------------------------------------------------
# Gobernanza
# ---------------------------------------------------------------------------

def sin_responsable(limite: int = 25) -> str:
    """Recursos sin tag de propietario en ninguna de sus grafias."""
    return (
        "resources | where isnull(tags.owner) and isnull(tags.Owner) "
        "and isnull(tags.OWNER) "
        "| project id, name, type, resourceGroup, subscriptionId "
        f"| limit {int(limite)}"
    )


def sin_expiracion(limite: int = 25) -> str:
    """Recursos no productivos sin fecha de expiracion declarada."""
    return (
        "resources "
        "| extend env = coalesce(tostring(tags.Environment), tostring(tags.environment), '') "
        "| where env in~ ('Dev', 'QA', 'Development', 'Staging', 'Test') "
        "| extend has_exp = isnotnull(tags.ExpirationDate) or isnotnull(tags.expirationDate) "
        "or isnotnull(tags.expires) "
        "| where not(has_exp) "
        "| project id, name, type, resourceGroup, subscriptionId "
        f"| limit {int(limite)}"
    )

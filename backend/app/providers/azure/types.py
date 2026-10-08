"""
Tipo canonico de cada tipo nativo de Azure (modelo canonico, ADR 0006).

Los desgloses y las reglas que valen para cualquier nube usan el canonico; el
detalle sigue mostrando el nativo. Un tipo sin mapeo queda en None: se
almacena igual y aparece por su tipo nativo.
"""

from typing import Optional

TIPOS = {
    "microsoft.compute/virtualmachines": "compute.vm",
    "microsoft.compute/virtualmachinescalesets": "compute.vm_scale_set",
    "microsoft.compute/disks": "storage.disk",
    "microsoft.compute/snapshots": "storage.snapshot",
    "microsoft.storage/storageaccounts": "storage.account",
    "microsoft.network/publicipaddresses": "network.public_ip",
    "microsoft.network/networksecuritygroups": "network.firewall_rules",
    "microsoft.network/virtualnetworks": "network.vnet",
    "microsoft.network/networkinterfaces": "network.interface",
    "microsoft.network/loadbalancers": "network.load_balancer",
    "microsoft.network/applicationgateways": "network.load_balancer",
    "microsoft.keyvault/vaults": "secrets.vault",
    "microsoft.sql/servers": "database.server",
    "microsoft.sql/servers/databases": "database.sql",
    "microsoft.dbforpostgresql/flexibleservers": "database.server",
    "microsoft.documentdb/databaseaccounts": "database.nosql",
    "microsoft.web/sites": "compute.app",
    "microsoft.web/serverfarms": "compute.app_plan",
    "microsoft.web/staticsites": "web.static_site",
    "microsoft.app/containerapps": "compute.container_app",
    "microsoft.app/managedenvironments": "compute.container_platform",
    "microsoft.app/jobs": "compute.job",
    "microsoft.containerservice/managedclusters": "kubernetes.cluster",
    "microsoft.containerregistry/registries": "container.registry",
    "microsoft.managedidentity/userassignedidentities": "identity.managed",
    "microsoft.insights/components": "observability.apm",
    "microsoft.operationalinsights/workspaces": "observability.logs",
}


def canonical_type(native_type: str) -> Optional[str]:
    return TIPOS.get((native_type or "").lower())

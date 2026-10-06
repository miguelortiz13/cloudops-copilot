"""
Precios de referencia de Azure: una sola tabla para toda la plataforma.

Estos importes son ordenes de magnitud publicos de la region East US 2 y se usan
**solo como respaldo**, cuando Cost Management no puede decir lo que costo de
verdad un recurso —falta de permisos sobre esa suscripcion, o limite de tasa—.
El gasto facturado siempre gana: ver `services/cost_service.py` y el campo
`cost_basis` del reporte de FinOps, que marca cada cifra como `billed` o
`estimated`.

Por que existe este modulo
--------------------------
La misma tabla vivia en tres sitios: el estimador por SKU del agente, el bloque
de precios escrito en prosa dentro del prompt de FinOps, y las constantes de
respaldo del servicio. Ya habian empezado a divergir —una IP publica costaba
3.60 en un lado y 3.65 en otro—, de modo que el panel, el chat y el reporte
podian dar tres cifras distintas del mismo recurso. Aqui hay una definicion, y
el prompt del modelo se genera a partir de ella con `tabla_para_prompt()`: si se
actualiza un precio, se actualiza tambien lo que el agente dice.

Al revisar precios, cambiar los valores de este archivo y nada mas.
"""

from typing import Any, Dict, Tuple

# Cada entrada es (Linux, Windows). Donde el sistema operativo no aplica, ambos
# valores coinciden.
APP_SERVICE_PLANS: Dict[str, Tuple[float, float]] = {
    "f1": (0.00, 0.00),
    "d1": (9.50, 9.50),
    "b1": (13.00, 55.00),
    "s1": (73.00, 140.00),
    "p1v3": (83.00, 146.00),
    "p2v3": (166.00, 292.00),
    "p3v3": (332.00, 584.00),
}

MAQUINAS_VIRTUALES: Dict[str, Tuple[float, float]] = {
    "b1s": (8.00, 15.00),
    "b2s": (30.00, 60.00),
    "b2ms": (40.00, 80.00),
    "b4ms": (80.00, 160.00),
    "d2s": (70.00, 140.00),
    "d4s": (140.00, 280.00),
}
VM_POR_DEFECTO: Tuple[float, float] = (40.00, 80.00)

SQL_DATABASES: Dict[str, float] = {
    "basic": 5.00,
    "s0": 15.00,
    "s1": 30.00,
    "s2": 75.00,
    "s3": 150.00,
    "gp_gen5": 368.00,
    "bc_gen5": 1000.00,
}
SQL_POR_DEFECTO = 15.00

# Discos gestionados: (Standard, Premium) por tramo de tamaño, y tarifa por GB
# para lo que exceda 512 GB.
DISCOS_POR_TRAMO = [
    (128, (4.00, 9.00)),
    (256, (8.00, 18.00)),
    (512, (16.00, 36.00)),
]
DISCO_POR_GB = (0.04, 0.08)

IP_PUBLICA_MES = 3.65          # direccion estatica estandar
SNAPSHOT_POR_GB_MES = 0.05
DISCO_POR_GB_MES = 0.05        # aprovisionado, Standard HDD/SSD
NIC_MES = 0.00                 # una NIC huerfana no factura por si sola

STORAGE_ACCOUNTS = {"standard": 5.00, "premium": 20.00}
KEY_VAULTS = {"standard": 3.00, "premium": 15.00}
CONTAINER_REGISTRIES = {"basic": 6.00, "standard": 20.00, "premium": 50.00}
STATIC_WEB_APPS = {"free": 0.00, "standard": 9.00}
BOT_SERVICE = {"f0": 0.00, "s1": 5.00}
APPLICATION_GATEWAY_MES = 180.00
AZURE_FIREWALL_MES = 900.00

# Vista que consume FinOpsService cuando tiene que estimar sin factura.
FALLBACK_PRICES = {
    "disk_per_gb_month": DISCO_POR_GB_MES,
    "public_ip_month": IP_PUBLICA_MES,
    "nic_month": NIC_MES,
    "app_service_plan_month": APP_SERVICE_PLANS["s1"][0],
    "snapshot_per_gb_month": SNAPSHOT_POR_GB_MES,
}

# Ahorro tipico al eliminar un disco huerfano, usado en los KPIs del panel
# cuando no hay factura por recurso: un disco de 128-256 GB Standard.
DISCO_HUERFANO_TIPICO_MES = 8.00


def _entero(valor: Any, por_defecto: int = 0) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return por_defecto


def costo_mensual_estimado(recurso: Dict[str, Any]) -> float:
    """
    Estimacion mensual en USD de un recurso, a partir de su tipo, SKU y
    propiedades.

    Devuelve 0.0 para los tipos que no facturan por si mismos (una web app
    corre dentro de su App Service Plan, un SQL Server es un contenedor de
    bases de datos) y para los que este catalogo no cubre: es preferible no
    sumar nada a inventar una cifra.
    """
    rtype = str(recurso.get("type", "")).lower()
    sku = recurso.get("sku") or {}
    sku_name = str(sku.get("name", "")).lower()
    sku_tier = str(sku.get("tier", "")).lower()
    props = recurso.get("properties") or {}

    if rtype == "microsoft.web/serverfarms":
        kind = str(recurso.get("kind", "")).lower()
        es_windows = (
            "windows" in kind
            or props.get("hyperV") is True
            or props.get("reserved") is False
        )
        indice = 1 if es_windows else 0
        for clave, precios in APP_SERVICE_PLANS.items():
            if clave in sku_name:
                return precios[indice]
        if "shared" in sku_name:
            return APP_SERVICE_PLANS["d1"][indice]
        if "free" in sku_name:
            return APP_SERVICE_PLANS["f1"][indice]
        if "premium" in sku_tier:
            return APP_SERVICE_PLANS["p1v3"][indice]
        if "standard" in sku_tier:
            return APP_SERVICE_PLANS["s1"][indice]
        if "basic" in sku_tier:
            return APP_SERVICE_PLANS["b1"][indice]
        return 0.0

    if rtype == "microsoft.sql/servers/databases":
        if "master" in str(recurso.get("name", "")).lower():
            return 0.0
        nombre_sku = sku_name or str(
            props.get("requestedServiceObjectiveName", "")
        ).lower()
        for clave, precio in SQL_DATABASES.items():
            if clave in nombre_sku:
                return precio
        if "generalpurpose" in nombre_sku:
            return SQL_DATABASES["gp_gen5"]
        if "businesscritical" in nombre_sku:
            return SQL_DATABASES["bc_gen5"]
        return SQL_POR_DEFECTO

    if rtype == "microsoft.web/staticsites":
        return STATIC_WEB_APPS["standard" if "standard" in sku_name else "free"]

    if rtype == "microsoft.botservice/botservices":
        return BOT_SERVICE["s1" if "s1" in sku_name else "f0"]

    if rtype == "microsoft.compute/disks":
        size_gb = _entero(props.get("diskSizeGB"), 128)
        indice = 1 if ("premium" in sku_name or "premium" in sku_tier) else 0
        for tope, precios in DISCOS_POR_TRAMO:
            if size_gb <= tope:
                return precios[indice]
        return size_gb * DISCO_POR_GB[indice]

    if rtype == "microsoft.network/publicipaddresses":
        return IP_PUBLICA_MES

    if rtype == "microsoft.compute/virtualmachines":
        os_disk = (props.get("storageProfile") or {}).get("osDisk") or {}
        es_windows = "windows" in str(os_disk.get("osType", "")).lower()
        indice = 1 if es_windows else 0
        tamano = str((props.get("hardwareProfile") or {}).get("vmSize", "")).lower()
        for clave, precios in MAQUINAS_VIRTUALES.items():
            if clave in tamano:
                return precios[indice]
        # Las familias D admiten varias grafias (d2s_v3, d2_v4, ...).
        if "d2_v" in tamano:
            return MAQUINAS_VIRTUALES["d2s"][indice]
        if "d4_v" in tamano:
            return MAQUINAS_VIRTUALES["d4s"][indice]
        return VM_POR_DEFECTO[indice]

    if rtype == "microsoft.compute/snapshots":
        return _entero(props.get("diskSizeGB")) * SNAPSHOT_POR_GB_MES

    if rtype == "microsoft.storage/storageaccounts":
        premium = "premium" in sku_name or "premium" in sku_tier
        return STORAGE_ACCOUNTS["premium" if premium else "standard"]

    if rtype == "microsoft.network/applicationgateways":
        return APPLICATION_GATEWAY_MES

    if rtype == "microsoft.network/azurefirewalls":
        return AZURE_FIREWALL_MES

    if rtype == "microsoft.containerregistry/registries":
        for clave, precio in CONTAINER_REGISTRIES.items():
            if clave in sku_name:
                return precio
        return CONTAINER_REGISTRIES["standard"]

    if rtype == "microsoft.keyvault/vaults":
        return KEY_VAULTS["premium" if "premium" in sku_name else "standard"]

    return 0.0


def tabla_para_prompt() -> str:
    """
    Los mismos precios, redactados para el prompt del agente FinOps.

    Se genera en vez de escribirse a mano para que el modelo no pueda citar una
    tarifa que el codigo ya no usa.
    """
    def par(precios: Tuple[float, float]) -> str:
        linux, windows = precios
        if linux == windows:
            return f"~${linux:.2f} USD/mes"
        return f"Linux ~${linux:.2f} | Windows ~${windows:.2f} USD/mes"

    lineas = ["TARIFAS DE REFERENCIA (USD/mes, East US 2, solo para estimar sin factura):", ""]

    lineas.append("App Service Plans (microsoft.web/serverfarms):")
    for clave, precios in APP_SERVICE_PLANS.items():
        lineas.append(f"  - {clave.upper()}: {par(precios)}")
    lineas.append(
        "  - Las web apps (microsoft.web/sites) cuestan $0: las cubre su plan. "
        "Si el sistema operativo no consta en 'pricing_properties', asumir Linux."
    )
    lineas.append("")

    lineas.append("Maquinas virtuales (microsoft.compute/virtualmachines):")
    for clave, precios in MAQUINAS_VIRTUALES.items():
        lineas.append(f"  - {clave.upper()}: {par(precios)}")
    lineas.append(f"  - Otros tamaños: {par(VM_POR_DEFECTO)}")
    lineas.append("")

    lineas.append("Bases de datos SQL (microsoft.sql/servers/databases):")
    for clave, precio in SQL_DATABASES.items():
        lineas.append(f"  - {clave.upper()}: ~${precio:.2f} USD/mes")
    lineas.append("  - El servidor (microsoft.sql/servers) no factura; las bases de datos si.")
    lineas.append("")

    lineas.append("Discos gestionados (microsoft.compute/disks):")
    for tope, (estandar, premium) in DISCOS_POR_TRAMO:
        lineas.append(f"  - hasta {tope} GB: Standard ~${estandar:.2f} | Premium ~${premium:.2f}")
    lineas.append(
        f"  - mas de 512 GB: ~${DISCO_POR_GB[0]:.2f}/GB Standard, "
        f"~${DISCO_POR_GB[1]:.2f}/GB Premium"
    )
    lineas.append("")

    lineas.append("Otros:")
    lineas.append(f"  - IP publica: ~${IP_PUBLICA_MES:.2f} c/u")
    lineas.append(f"  - Snapshots: ~${SNAPSHOT_POR_GB_MES:.2f} por GB")
    lineas.append(
        f"  - Storage Account: Standard ~${STORAGE_ACCOUNTS['standard']:.2f} | "
        f"Premium ~${STORAGE_ACCOUNTS['premium']:.2f}"
    )
    lineas.append(
        f"  - Key Vault: Standard ~${KEY_VAULTS['standard']:.2f} | "
        f"Premium ~${KEY_VAULTS['premium']:.2f}"
    )
    lineas.append(
        "  - Container Registry: "
        + " | ".join(f"{k.capitalize()} ~${v:.2f}" for k, v in CONTAINER_REGISTRIES.items())
    )
    lineas.append(
        f"  - Static Web App: Free $0.00 | Standard ~${STATIC_WEB_APPS['standard']:.2f}"
    )
    lineas.append(f"  - Application Gateway: ~${APPLICATION_GATEWAY_MES:.2f}")
    lineas.append(f"  - Azure Firewall: ~${AZURE_FIREWALL_MES:.2f}")
    lineas.append(f"  - NIC huerfana: ${NIC_MES:.2f} (no factura por si sola)")

    return "\n".join(lineas)

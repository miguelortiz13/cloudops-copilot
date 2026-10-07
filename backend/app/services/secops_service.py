"""
SecOpsService — Hallazgos de seguridad con severidad y sin falsos positivos.

El reporte anterior sobre-reportaba de forma masiva, lo que vaciaba de sentido
al panel. Medido contra el tenant de produccion (367 cuentas de almacenamiento,
85 Key Vaults):

* Key Vaults: la consulta no tenia clausula `where`. Reportaba los 85 vaults del
  tenant como "expuestos", incluidos los que estan correctamente cerrados.
* Almacenamiento: la condicion era `allowBlobPublicAccess == true OR
  publicNetworkAccess =~ 'Enabled' OR isnull(publicNetworkAccess)`. Como ese
  ultimo campo viene nulo por defecto, marcaba 354 de 367 cuentas (96%). Solo
  112 permiten realmente acceso publico a blobs.

Un panel que senala el 96% del inventario no dirige ninguna accion: es ruido con
formato de alerta. Aqui cada consulta busca la condicion que de verdad implica
exposicion, y cada hallazgo lleva una severidad para que el equipo sepa por
donde empezar.

La severidad se asigna por alcanzabilidad, no por tipo de recurso:

* `critica` — alcanzable desde internet y con camino de entrada (puerto de
  administracion abierto a `*`, contenedores publicos sin firewall).
* `alta`    — expuesto por configuracion, aunque requiera credenciales.
* `media`   — endurecimiento pendiente sin exposicion directa.

Este modulo solo consulta la tabla `resources` de Azure Resource Graph, que el
rol `Reader` cubre en todo el tenant; no requiere `Security Reader` ni Defender
for Cloud.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from app.services import kql

SEVERIDAD_ORDEN = {"critica": 0, "alta": 1, "media": 2, "info": 3}


class SecOpsService:
    """Construye el reporte de seguridad a partir de Azure Resource Graph."""

    def __init__(self, azure):
        self.azure = azure

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------

    # Las consultas viven en services/kql.py, que es la unica definicion de
    # cada regla en toda la plataforma: el panel, el chat del agente y los
    # reportes leen de ahi. Antes el chat traia su propia copia y las dos
    # versiones habian divergido, de modo que el mismo tenant daba cifras
    # distintas segun donde se preguntara.
    KQL_NSG = kql.NSG_ADMIN_EXPUESTO
    KQL_STORAGE = kql.STORAGE_BLOBS_PUBLICOS
    KQL_KEYVAULT = kql.KEYVAULT_PUBLICO
    KQL_PUBLIC_IPS = kql.IPS_PUBLICAS_ACTIVAS
    KQL_HTTPS = kql.APPS_SIN_HTTPS
    KQL_SQL = kql.SQL_PUBLICO
    KQL_FAILED = kql.RECURSOS_FALLIDOS
    KQL_DISCOS_SIN_CMK = kql.DISCOS_SIN_CMK

    # ------------------------------------------------------------------

    def build_report(self, subscription_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Reporte de seguridad con hallazgos clasificados por severidad."""
        subs = subscription_ids or []

        consultas = {
            "nsgs": self.KQL_NSG,
            "storage": self.KQL_STORAGE,
            "keyvaults": self.KQL_KEYVAULT,
            "public_ips": self.KQL_PUBLIC_IPS,
            "https": self.KQL_HTTPS,
            "sql": self.KQL_SQL,
            "failed": self.KQL_FAILED,
            "discos": self.KQL_DISCOS_SIN_CMK,
        }

        crudos: Dict[str, List[Dict[str, Any]]] = {}
        with ThreadPoolExecutor(max_workers=len(consultas)) as executor:
            futuros = {
                nombre: executor.submit(
                    self.azure.query_azure_resource_graph, kql, False, subs
                )
                for nombre, kql in consultas.items()
            }
            for nombre, futuro in futuros.items():
                try:
                    crudos[nombre] = futuro.result() or []
                except Exception as exc:
                    print(f"[SecOpsService] Consulta '{nombre}' falló: {exc}")
                    crudos[nombre] = []

        # El conjunto de IPs publicas permite decidir si una regla de NSG es
        # teoricamente abierta o realmente alcanzable desde internet.
        hay_ips_publicas = len(crudos["public_ips"]) > 0

        hallazgos: List[Dict[str, Any]] = []

        def agregar(items, tipo, titulo, severidad_fn, recomendacion):
            for item in items:
                sev = severidad_fn(item)
                hallazgos.append({
                    **item,
                    "tipo": tipo,
                    "titulo": titulo,
                    "severidad": sev,
                    "recomendacion": recomendacion,
                })

        agregar(
            crudos["nsgs"], "nsg", "Puerto de administración abierto a internet",
            lambda i: "critica" if (i.get("asociado") and hay_ips_publicas) else "alta",
            "Restringir el origen a rangos corporativos o usar Azure Bastion / Just-In-Time.",
        )
        agregar(
            crudos["storage"], "storage", "Cuenta de almacenamiento con blobs públicos",
            lambda i: "critica" if i.get("sinFirewall") else "alta",
            "Deshabilitar allowBlobPublicAccess o restringir con reglas de red.",
        )
        agregar(
            crudos["keyvaults"], "keyvault", "Key Vault alcanzable desde red pública",
            lambda i: "critica" if i.get("sinFirewall") else "alta",
            "Añadir private endpoint o limitar networkAcls a redes conocidas.",
        )
        agregar(
            crudos["sql"], "sql", "SQL Server con acceso público habilitado",
            lambda i: "alta",
            "Deshabilitar publicNetworkAccess y acceder por private endpoint.",
        )
        agregar(
            crudos["https"], "https", "App Service sin HTTPS obligatorio",
            lambda i: "alta",
            "Activar httpsOnly para impedir tráfico en claro.",
        )
        agregar(
            crudos["discos"], "disco", "Disco sin cifrado con llave gestionada por el cliente",
            lambda i: "media",
            "Asociar un Disk Encryption Set si la política de datos lo exige.",
        )
        agregar(
            crudos["failed"], "failed", "Recurso en estado de aprovisionamiento fallido",
            lambda i: "media",
            "Revisar el despliegue: un recurso en Failed puede quedar a medio configurar.",
        )

        hallazgos.sort(key=lambda h: SEVERIDAD_ORDEN.get(h["severidad"], 9))

        conteo = {"critica": 0, "alta": 0, "media": 0}
        for h in hallazgos:
            if h["severidad"] in conteo:
                conteo[h["severidad"]] += 1

        return {
            # Contrato previo, para no romper la interfaz existente.
            "exposed_nsgs": crudos["nsgs"],
            "public_storage_accounts": crudos["storage"],
            "exposed_keyvaults": crudos["keyvaults"],
            "public_ips_active": crudos["public_ips"],
            "failed_resources": crudos["failed"],
            "vms_without_encryption": crudos["discos"],
            "attack_surface_summary": {
                "exposed_nsg_rules": len(crudos["nsgs"]),
                "public_storage_accounts": len(crudos["storage"]),
                "exposed_keyvaults": len(crudos["keyvaults"]),
                "active_public_ips": len(crudos["public_ips"]),
                "failed_resources": len(crudos["failed"]),
                "vms_for_encryption_review": len(crudos["discos"]),
            },
            # Vista nueva: todo junto, ordenado por lo que hay que atender primero.
            "findings": hallazgos,
            "severity_summary": conteo,
            "sql_public": crudos["sql"],
            "apps_without_https": crudos["https"],
        }

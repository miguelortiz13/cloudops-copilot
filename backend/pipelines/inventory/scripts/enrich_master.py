#!/usr/bin/env python3
# enrich_master.py — Agrega recursos nuevos y enriquece columnas en 09_analysis_master
import csv, json
from datetime import date
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from _paths import EXCEL, EXPORTS, SNAPSHOTS  # noqa: F401
SHEET  = "09_analysis_master"
TODAY  = date.today().isoformat()
VERSION = "1.1"

# ── Mapa subscriptionId → nombre ──────────────────────────────────────────
SUBS: dict[str, str] = {}
with open(EXPORTS / "subscriptions.csv", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        SUBS[r["id"]] = r["name"]

# ── Mapa tipo → (domain, subdomain) ───────────────────────────────────────
DOMAIN_MAP: dict[str, tuple[str, str]] = {
    # DATA
    "microsoft.documentdb/databaseaccounts":          ("data", "db_account"),
    "microsoft.sql/servers":                          ("data", "sql_server"),
    "microsoft.sql/servers/databases":                ("data", "sql_db"),
    "microsoft.sql/servers/elasticpools":             ("data", "sql_elastic_pool"),
    "microsoft.sql/servers/jobagents":                ("data", "sql_server"),
    "microsoft.dbforpostgresql/flexibleservers":      ("data", "pgsql"),
    "microsoft.cache/redis":                          ("data", "redis"),
    "microsoft.cache/redisenterprise":                ("data", "redis"),
    "microsoft.storage/storageaccounts":              ("data", "storage"),
    "microsoft.compute/disks":                        ("data", "disk"),
    "microsoft.compute/snapshots":                    ("data", "disk"),
    "microsoft.databricks/workspaces":                ("data", "databricks"),
    "microsoft.datafactory/factories":                ("data", "data_factory"),
    "microsoft.purview/accounts":                     ("data", "purview"),
    "microsoft.fabric/capacities":                    ("data", "fabric"),
    "microsoft.analysisservices/servers":             ("data", "analysis_services"),
    "microsoft.powerbidedicated/capacities":          ("data", "powerbi"),
    "microsoft.search/searchservices":                ("data", "search"),
    "microsoft.storagemover/storagemovers":           ("data", "storage"),
    "microsoft.storagesync/storagesyncservices":      ("data", "storage"),
    "microsoft.dataprotection/backupvaults":          ("data", "backup"),
    "microsoft.recoveryservices/vaults":              ("data", "backup"),
    "microsoft.datamigration/sqlmigrationservices":   ("data", "sql_server"),
    # PLATFORM
    "microsoft.web/sites":                            ("platform", "app_services"),
    "microsoft.web/sites/slots":                      ("platform", "app_services"),
    "microsoft.web/serverfarms":                      ("platform", "app_service_plan"),
    "microsoft.web/staticsites":                      ("platform", "app_services"),
    "microsoft.web/certificates":                     ("platform", "app_services"),
    "microsoft.web/connections":                      ("platform", "app_services"),
    "microsoft.web/customapis":                       ("platform", "app_services"),
    "microsoft.app/containerapps":                    ("platform", "container_apps"),
    "microsoft.app/jobs":                             ("platform", "jobs"),
    "microsoft.app/managedenvironments":              ("platform", "container_app_environment"),
    "microsoft.app/managedenvironments/managedcertificates": ("platform", "container_app_managed_certificate"),
    "microsoft.containerservice/managedclusters":     ("platform", "aks"),
    "microsoft.containerregistry/registries":         ("platform", "acr"),
    "microsoft.containerregistry/registries/webhooks":("platform", "acr"),
    "microsoft.compute/virtualmachines":              ("platform", "vm"),
    "microsoft.compute/virtualmachinescalesets":      ("platform", "vm"),
    "microsoft.compute/virtualmachines/extensions":   ("platform", "vm"),
    "microsoft.compute/galleries":                    ("platform", "vm"),
    "microsoft.compute/galleries/images":             ("platform", "vm"),
    "microsoft.compute/galleries/images/versions":    ("platform", "vm"),
    "microsoft.compute/images":                       ("platform", "vm"),
    "microsoft.compute/sshpublickeys":                ("platform", "vm"),
    "microsoft.compute/restorepointcollections":      ("platform", "vm"),
    "microsoft.sqlvirtualmachine/sqlvirtualmachines": ("platform", "vm"),
    "microsoft.containerinstance/containergroups":    ("platform", "container_grp"),
    "microsoft.machinelearningservices/workspaces":   ("platform", "ml_workspace"),
    "microsoft.cognitiveservices/accounts":           ("platform", "cognitive_services"),
    "microsoft.cognitiveservices/accounts/projects":  ("platform", "cognitive_services"),
    "microsoft.botservice/botservices":               ("platform", "cognitive_services"),
    "microsoft.virtualmachineimages/imagetemplates":  ("platform", "vm"),
    "microsoft.devopsinfrastructure/pools":           ("platform", "devops"),
    "microsoft.loadtestservice/loadtests":            ("platform", "devops"),
    "microsoft.visualstudio/account":                 ("platform", "devops"),
    "microsoft.desktopvirtualization/applicationgroups": ("platform", "vm"),
    "microsoft.desktopvirtualization/hostpools":      ("platform", "vm"),
    "microsoft.desktopvirtualization/workspaces":     ("platform", "vm"),
    # NETWORKING
    "microsoft.network/virtualnetworks":              ("networking", "vnet"),
    "microsoft.network/networksecuritygroups":        ("networking", "nsg"),
    "microsoft.network/publicipaddresses":            ("networking", "public_ip"),
    "microsoft.network/networkinterfaces":            ("networking", "nic"),
    "microsoft.network/loadbalancers":                ("networking", "load_balancer"),
    "microsoft.network/routetables":                  ("networking", "routetables"),
    "microsoft.network/virtualnetworkgateways":       ("networking", "gateway-webapp"),
    "microsoft.network/localnetworkgateways":         ("networking", "localnetworkgateways"),
    "microsoft.network/connections":                  ("networking", "connection"),
    "microsoft.network/privatednszones":              ("networking", "privatednszones"),
    "microsoft.network/privatednszones/virtualnetworklinks": ("networking", "privatednszones/virtualnetworklinks"),
    "microsoft.network/dnszones":                     ("networking", "dns"),
    "microsoft.network/bastionhosts":                 ("networking", "bastion"),
    "microsoft.network/natgateways":                  ("networking", "vnet"),
    "microsoft.network/networkwatchers":              ("networking", "networkwatchers"),
    "microsoft.network/frontdoors":                   ("networking", "frontdoor"),
    "microsoft.network/frontdoorwebapplicationfirewallpolicies": ("networking", "frontdoor-webapp-police"),
    "microsoft.network/applicationgatewaywebapplicationfirewallpolicies": ("networking", "frontdoor-webapp-police"),
    "microsoft.network/privateendpoints":             ("networking", "nic"),
    "microsoft.cdn/profiles":                         ("networking", "frontdoor"),
    "microsoft.cdn/profiles/afdendpoints":            ("networking", "frontdoor"),
    # SECURITY
    "microsoft.keyvault/vaults":                      ("security", "key_vault"),
    "microsoft.managedidentity/userassignedidentities": ("security", "managed_identity"),
    "microsoft.aad/domainservices":                   ("security", "entra_domain_services"),
    "microsoft.azureactivedirectory/b2cdirectories":  ("security", "entra_domain_services"),
    "microsoft.codesigning/codesigningaccounts":      ("security", "managed_identity"),
    "microsoft.easm/workspaces":                      ("security", "managed_identity"),
    "microsoft.security/automations":                 ("security", "managed_identity"),
    # OBSERVABILITY / INTEGRATION
    "microsoft.insights/components":                  ("observability", "app_insights"),
    "microsoft.insights/actiongroups":                ("observability", "app_insights"),
    "microsoft.insights/activitylogalerts":           ("observability", "app_insights"),
    "microsoft.insights/autoscalesettings":           ("observability", "app_insights"),
    "microsoft.insights/metricalerts":                ("observability", "app_insights"),
    "microsoft.insights/scheduledqueryrules":         ("observability", "app_insights"),
    "microsoft.insights/datacollectionrules":         ("observability", "app_insights"),
    "microsoft.insights/datacollectionendpoints":     ("observability", "app_insights"),
    "microsoft.insights/workbooks":                   ("observability", "app_insights"),
    "microsoft.alertsmanagement/prometheusrulegroups":("observability", "app_insights"),
    "microsoft.alertsmanagement/smartdetectoralertrules": ("observability", "app_insights"),
    "microsoft.operationalinsights/workspaces":       ("observability", "log_analytics"),
    "microsoft.operationsmanagement/solutions":       ("observability", "log_analytics"),
    "microsoft.monitor/accounts":                     ("observability", "log_analytics"),
    "microsoft.servicebus/namespaces":                ("integration", "service_bus"),
    "microsoft.relay/namespaces":                     ("integration", "service_bus"),
    "microsoft.eventhub/namespaces":                  ("integration", "service_bus"),
    "microsoft.eventgrid/systemtopics":               ("integration", "service_bus"),
    "microsoft.eventgrid/topics":                     ("integration", "service_bus"),
    "microsoft.logic/workflows":                      ("integration", "service_bus"),
    "microsoft.apimanagement/service":                ("integration", "api_management"),
    "microsoft.communication/communicationservices":  ("integration", "service_bus"),
    "microsoft.signalrservice/signalr":               ("integration", "service_bus"),
    "microsoft.signalrservice/webpubsub":             ("integration", "service_bus"),
    "microsoft.web/connections":                      ("integration", "service_bus"),
    # HEALTHCARE
    "microsoft.healthcareapis/workspaces":            ("platform", "healthcare_workspace"),
    "microsoft.healthcareapis/workspaces/dicomservices": ("platform", "dicom_service"),
    "microsoft.healthcareapis/workspaces/fhirservices": ("platform", "fhir_service"),
    # DEVCENTER
    "microsoft.devcenter/devcenters":                 ("devcenter", "devcenter"),
    "microsoft.devcenter/networkconnections":         ("devcenter", "networkconnections"),
    "microsoft.devcenter/projects":                   ("devcenter", "devcenter"),
    "microsoft.devtestlab/schedules":                 ("devcenter", "devcenter"),
    # MISC / GOVERNANCE
    "microsoft.automation/automationaccounts":        ("platform", "automation"),
    "microsoft.automation/automationaccounts/runbooks": ("platform", "automation"),
    "microsoft.portal/dashboards":                    ("platform", "automation"),
    "microsoft.resourcegraph/queries":                ("platform", "automation"),
    "microsoft.saas/resources":                       ("platform", "automation"),
    "microsoft.migrate/movecollections":              ("platform", "automation"),
    "microsoft.certificateregistration/certificateorders": ("security", "key_vault"),
}

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(bold=True, color="FFFFFF")
NEW_FILL    = PatternFill("solid", fgColor="E2EFDA")  # verde claro para filas nuevas


def get_domain(rtype: str) -> tuple[str, str]:
    return DOMAIN_MAP.get(rtype.lower(), ("", ""))


def main():
    # ── Cargar recursos completos desde CSV ───────────────────────────────
    full: dict[str, dict] = {}
    with open(EXPORTS / "resources_full.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            full[r["id"]] = r

    wb = openpyxl.load_workbook(EXCEL)
    if "Hoja1" in wb.sheetnames:
        del wb["Hoja1"]
    ws = wb[SHEET]

    # ── Leer headers actuales y agregar columnas nuevas si faltan ─────────
    header_row = [c.value for c in ws[1]]
    NEW_COLS = ["resource_id", "subscription_name", "extraction_date",
                "inventory_version", "review_status"]
    for col in NEW_COLS:
        if col not in header_row:
            header_row.append(col)
            ws.cell(row=1, column=len(header_row), value=col)

    col_idx = {h: i+1 for i, h in enumerate(header_row) if h}

    # Aplicar estilo a headers nuevos
    for col in NEW_COLS:
        if col in col_idx:
            cell = ws.cell(row=1, column=col_idx[col])
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center")

    # ── Recopilar IDs ya existentes en master y enriquecer filas ──────────
    existing_ids: set[str] = set()
    for row in ws.iter_rows(min_row=2):
        # Leer id desde columna 'id' o 'resource_id'
        name_val  = row[col_idx["name"]-1].value if "name" in col_idx else None
        type_val  = row[col_idx["type"]-1].value if "type" in col_idx else None
        sub_val   = row[col_idx["subscriptionId"]-1].value if "subscriptionId" in col_idx else None

        # Buscar resource_id en full por name+type+subscription
        rid = None
        if "resource_id" in col_idx:
            rid = row[col_idx["resource_id"]-1].value
        if not rid:
            rg_val = row[col_idx["resourceGroup"]-1].value if "resourceGroup" in col_idx else None
            loc_val = row[col_idx["location"]-1].value if "location" in col_idx else None
            # intentar encontrar por name+type+subscriptionId+resourceGroup+location
            for fid, fr in full.items():
                if (fr.get("name") == name_val and
                    fr.get("type","").lower() == (type_val or "").lower() and
                    fr.get("subscriptionId") == sub_val and
                    (not rg_val or str(fr.get("resourceGroup")).lower() == str(rg_val).lower()) and
                    (not loc_val or str(fr.get("location")).lower() == str(loc_val).lower())):
                    rid = fid
                    break

        if rid:
            existing_ids.add(rid)
            ws.cell(row=row[0].row, column=col_idx["resource_id"], value=rid)

        # domain / subdomain
        if type_val:
            d, sd = get_domain(type_val)
            if d and not row[col_idx["domain"]-1].value:
                ws.cell(row=row[0].row, column=col_idx["domain"], value=d)
            if sd and not row[col_idx["subdomain"]-1].value:
                ws.cell(row=row[0].row, column=col_idx["subdomain"], value=sd)

        # subscription_name
        if sub_val and not row[col_idx["subscription_name"]-1].value:
            ws.cell(row=row[0].row, column=col_idx["subscription_name"],
                    value=SUBS.get(sub_val, sub_val))

        # extraction_date
        if not row[col_idx["extraction_date"]-1].value:
            ws.cell(row=row[0].row, column=col_idx["extraction_date"], value=TODAY)

        # inventory_version
        if not row[col_idx["inventory_version"]-1].value:
            ws.cell(row=row[0].row, column=col_idx["inventory_version"], value=VERSION)

        # review_status
        if not row[col_idx["review_status"]-1].value:
            ws.cell(row=row[0].row, column=col_idx["review_status"], value="pendiente")

    # ── Agregar recursos nuevos ───────────────────────────────────────────
    new_count = 0
    from finalize_master import TYPE_MAP
    for rid, r in full.items():
        if rid in existing_ids:
            continue
        rtype = r.get("type", "")
        sub   = r.get("subscriptionId", "")
        d, sd = get_domain(rtype)
        module, priority, tf_import = TYPE_MAP.get(rtype.lower(), ("", "Media", "Si"))

        new_row = [None] * len(header_row)
        def s(field, val):
            if field in col_idx: new_row[col_idx[field]-1] = val

        s("name",                    r.get("name",""))
        s("type",                    rtype)
        s("resourceGroup",           r.get("resourceGroup",""))
        s("subscriptionId",          sub)
        s("subscription_name",       SUBS.get(sub, sub))
        s("location",                r.get("location",""))
        s("resource_id",             rid)
        s("domain",                  d)
        s("subdomain",               sd)
        s("environment",             "")
        s("owner_confirmed",         "Por confirmar")
        s("provisioning_method",     "unknown")
        s("adoption_priority",       priority)
        s("requires_terraform_import", tf_import)
        s("candidate_module",        module)
        s("evidence_source",         "tags" if r.get("tags") else "sin evidencia aún")
        s("known_drift",             "Desconocido")
        s("tags",                    r.get("tags",""))
        s("extraction_date",         TODAY)
        s("inventory_version",       VERSION)
        s("review_status",           "pendiente")

        ws.append(new_row)
        # highlight new row
        new_row_idx = ws.max_row
        for col in range(1, len(header_row)+1):
            ws.cell(row=new_row_idx, column=col).fill = NEW_FILL
        new_count += 1

    print(f"  ✓ Recursos existentes enriquecidos: {len(existing_ids)}")
    print(f"  + Recursos nuevos agregados:        {new_count}")
    print(f"  🔒 {SHEET} actualizada (sin borrar datos manuales)")

    wb.save(EXCEL)
    print(f"\n✅ Excel guardado: {EXCEL.name}")


if __name__ == "__main__":
    main()

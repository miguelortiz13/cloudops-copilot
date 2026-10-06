#!/usr/bin/env python3
# finalize_master.py — Rellena candidate_module, adoption_priority y requires_terraform_import
# según el tipo de recurso. Solo sobreescribe campos vacíos o "Por confirmar".
import openpyxl
from pathlib import Path

from _paths import EXCEL, EXPORTS, SNAPSHOTS  # noqa: F401
SHEET = "09_analysis_master"

# ── Mapa tipo → (candidate_module, adoption_priority, requires_terraform_import)
# adoption_priority: Alta | Media | Baja
# requires_terraform_import: Si | No
TYPE_MAP: dict[str, tuple[str, str, str]] = {
    # ── DATA ──────────────────────────────────────────────────────────────
    "microsoft.documentdb/databaseaccounts":           ("module/cosmosdb-account",        "Alta",  "Si"),
    "microsoft.sql/servers":                           ("module/sql-server",               "Alta",  "Si"),
    "microsoft.sql/servers/databases":                 ("module/sql-database",             "Alta",  "Si"),
    "microsoft.sql/servers/elasticpools":              ("module/sql-elastic-pool",         "Media", "Si"),
    "microsoft.sql/servers/jobagents":                 ("module/sql-job-agent",            "Baja",  "Si"),
    "microsoft.dbforpostgresql/flexibleservers":       ("module/postgresql-flexible",      "Alta",  "Si"),
    "microsoft.cache/redis":                           ("module/redis-cache",              "Alta",  "Si"),
    "microsoft.cache/redisenterprise":                 ("module/redis-enterprise",         "Alta",  "Si"),
    "microsoft.storage/storageaccounts":               ("module/storage-account",          "Alta",  "Si"),
    "microsoft.compute/disks":                         ("module/managed-disk",             "Media", "Si"),
    "microsoft.compute/snapshots":                     ("module/managed-disk",             "Baja",  "No"),
    "microsoft.databricks/workspaces":                 ("module/databricks-workspace",     "Media", "Si"),
    "microsoft.datafactory/factories":                 ("module/data-factory",             "Media", "Si"),
    "microsoft.purview/accounts":                      ("module/purview-account",          "Media", "Si"),
    "microsoft.fabric/capacities":                     ("module/fabric-capacity",          "Media", "Si"),
    "microsoft.analysisservices/servers":              ("module/analysis-services",        "Baja",  "Si"),
    "microsoft.powerbidedicated/capacities":           ("module/powerbi-dedicated",        "Baja",  "Si"),
    "microsoft.search/searchservices":                 ("module/search-service",           "Media", "Si"),
    "microsoft.storagemover/storagemovers":            ("module/storage-mover",            "Baja",  "Si"),
    "microsoft.storagesync/storagesyncservices":       ("module/storage-sync",             "Baja",  "Si"),
    "microsoft.dataprotection/backupvaults":           ("module/backup-vault",             "Media", "Si"),
    "microsoft.recoveryservices/vaults":               ("module/recovery-vault",           "Media", "Si"),
    "microsoft.datamigration/sqlmigrationservices":    ("module/sql-migration-service",    "Baja",  "No"),
    # ── PLATFORM ──────────────────────────────────────────────────────────
    "microsoft.web/sites":                             ("module/app-service",              "Alta",  "Si"),
    "microsoft.web/sites/slots":                       ("module/app-service-slot",         "Media", "Si"),
    "microsoft.web/serverfarms":                       ("module/app-service-plan",         "Alta",  "Si"),
    "microsoft.web/staticsites":                       ("module/static-web-app",           "Media", "Si"),
    "microsoft.web/certificates":                      ("module/app-service-certificate",  "Baja",  "No"),
    "microsoft.web/connections":                       ("module/logic-app-connection",     "Baja",  "No"),
    "microsoft.web/customapis":                        ("module/logic-app-custom-api",     "Baja",  "No"),
    "microsoft.app/containerapps":                     ("module/container-app",            "Alta",  "Si"),
    "microsoft.app/jobs":                              ("module/container-app-job",        "Media", "Si"),
    "microsoft.app/managedenvironments":               ("module/container-app-environment","Alta",  "Si"),
    "microsoft.app/managedenvironments/managedcertificates": ("module/container-app-certificate", "Baja", "No"),
    "microsoft.containerservice/managedclusters":      ("module/aks-cluster",              "Alta",  "Si"),
    "microsoft.containerregistry/registries":          ("module/container-registry",       "Alta",  "Si"),
    "microsoft.containerregistry/registries/webhooks": ("module/container-registry",       "Baja",  "No"),
    "microsoft.compute/virtualmachines":               ("module/virtual-machine",          "Alta",  "Si"),
    "microsoft.compute/virtualmachinescalesets":       ("module/vmss",                     "Alta",  "Si"),
    "microsoft.compute/virtualmachines/extensions":    ("module/vm-extension",             "Baja",  "No"),
    "microsoft.compute/galleries":                     ("module/compute-gallery",          "Baja",  "Si"),
    "microsoft.compute/galleries/images":              ("module/compute-gallery",          "Baja",  "Si"),
    "microsoft.compute/galleries/images/versions":     ("module/compute-gallery",          "Baja",  "No"),
    "microsoft.compute/images":                        ("module/compute-image",            "Baja",  "No"),
    "microsoft.compute/sshpublickeys":                 ("module/ssh-public-key",           "Baja",  "No"),
    "microsoft.compute/restorepointcollections":       ("module/restore-point-collection", "Baja",  "No"),
    "microsoft.sqlvirtualmachine/sqlvirtualmachines":  ("module/sql-virtual-machine",      "Media", "Si"),
    "microsoft.containerinstance/containergroups":     ("module/container-instance",       "Media", "Si"),
    "microsoft.machinelearningservices/workspaces":    ("module/ml-workspace",             "Media", "Si"),
    "microsoft.cognitiveservices/accounts":            ("module/cognitive-services",       "Media", "Si"),
    "microsoft.cognitiveservices/accounts/projects":   ("module/cognitive-services",       "Baja",  "No"),
    "microsoft.botservice/botservices":                ("module/bot-service",              "Baja",  "Si"),
    "microsoft.virtualmachineimages/imagetemplates":   ("module/image-builder",            "Baja",  "No"),
    "microsoft.devopsinfrastructure/pools":            ("module/devops-pool",              "Media", "Si"),
    "microsoft.loadtestservice/loadtests":             ("module/load-test",                "Baja",  "No"),
    "microsoft.visualstudio/account":                  ("module/devops-organization",      "Baja",  "No"),
    "microsoft.desktopvirtualization/applicationgroups": ("module/avd-application-group",  "Media", "Si"),
    "microsoft.desktopvirtualization/hostpools":       ("module/avd-host-pool",            "Media", "Si"),
    "microsoft.desktopvirtualization/workspaces":      ("module/avd-workspace",            "Media", "Si"),
    "microsoft.healthcareapis/workspaces":             ("module/healthcare-workspace",     "Alta",  "Si"),
    "microsoft.healthcareapis/workspaces/dicomservices": ("module/dicom-service",          "Alta",  "Si"),
    "microsoft.healthcareapis/workspaces/fhirservices": ("module/fhir-service",            "Alta",  "Si"),
    "microsoft.automation/automationaccounts":         ("module/automation-account",       "Media", "Si"),
    "microsoft.automation/automationaccounts/runbooks": ("module/automation-runbook",      "Baja",  "No"),
    "microsoft.devtestlab/schedules":                  ("module/devtest-schedule",         "Baja",  "No"),
    "microsoft.migrate/movecollections":               ("module/resource-mover",           "Baja",  "No"),
    "microsoft.portal/dashboards":                     ("module/portal-dashboard",         "Baja",  "No"),
    "microsoft.resourcegraph/queries":                 ("module/resource-graph-query",     "Baja",  "No"),
    "microsoft.saas/resources":                        ("module/saas-resource",            "Baja",  "No"),
    # ── NETWORKING ────────────────────────────────────────────────────────
    "microsoft.network/virtualnetworks":               ("module/virtual-network",          "Alta",  "Si"),
    "microsoft.network/networksecuritygroups":         ("module/network-security-group",   "Alta",  "Si"),
    "microsoft.network/publicipaddresses":             ("module/public-ip",                "Media", "Si"),
    "microsoft.network/networkinterfaces":             ("module/network-interface",        "Media", "Si"),
    "microsoft.network/loadbalancers":                 ("module/load-balancer",            "Alta",  "Si"),
    "microsoft.network/routetables":                   ("module/route-table",              "Media", "Si"),
    "microsoft.network/virtualnetworkgateways":        ("module/vnet-gateway",             "Alta",  "Si"),
    "microsoft.network/localnetworkgateways":          ("module/local-network-gateway",    "Media", "Si"),
    "microsoft.network/connections":                   ("module/vpn-connection",           "Media", "Si"),
    "microsoft.network/privatednszones":               ("module/private-dns-zone",         "Media", "Si"),
    "microsoft.network/privatednszones/virtualnetworklinks": ("module/private-dns-zone",   "Baja",  "No"),
    "microsoft.network/dnszones":                      ("module/dns-zone",                 "Media", "Si"),
    "microsoft.network/bastionhosts":                  ("module/bastion-host",             "Media", "Si"),
    "microsoft.network/natgateways":                   ("module/nat-gateway",              "Media", "Si"),
    "microsoft.network/networkwatchers":               ("module/network-watcher",          "Baja",  "No"),
    "microsoft.network/frontdoors":                    ("module/front-door",               "Alta",  "Si"),
    "microsoft.network/frontdoorwebapplicationfirewallpolicies": ("module/waf-policy",     "Media", "Si"),
    "microsoft.network/applicationgatewaywebapplicationfirewallpolicies": ("module/waf-policy", "Media", "Si"),
    "microsoft.network/privateendpoints":              ("module/private-endpoint",         "Media", "Si"),
    "microsoft.cdn/profiles":                          ("module/cdn-profile",              "Media", "Si"),
    "microsoft.cdn/profiles/afdendpoints":             ("module/cdn-afd-endpoint",         "Media", "Si"),
    # ── SECURITY ──────────────────────────────────────────────────────────
    "microsoft.keyvault/vaults":                       ("module/key-vault",                "Alta",  "Si"),
    "microsoft.managedidentity/userassignedidentities": ("module/user-assigned-identity",  "Alta",  "Si"),
    "microsoft.aad/domainservices":                    ("module/aad-domain-services",      "Alta",  "Si"),
    "microsoft.azureactivedirectory/b2cdirectories":   ("module/b2c-directory",            "Media", "Si"),
    "microsoft.codesigning/codesigningaccounts":       ("module/code-signing-account",     "Baja",  "No"),
    "microsoft.easm/workspaces":                       ("module/easm-workspace",           "Baja",  "No"),
    "microsoft.certificateregistration/certificateorders": ("module/app-service-certificate", "Baja", "No"),
    # ── OBSERVABILITY ─────────────────────────────────────────────────────
    "microsoft.insights/components":                   ("module/app-insights",             "Alta",  "Si"),
    "microsoft.insights/actiongroups":                 ("module/monitor-action-group",     "Media", "No"),
    "microsoft.insights/activitylogalerts":            ("module/monitor-activity-alert",   "Baja",  "No"),
    "microsoft.insights/autoscalesettings":            ("module/autoscale-setting",        "Baja",  "No"),
    "microsoft.insights/metricalerts":                 ("module/monitor-metric-alert",     "Baja",  "No"),
    "microsoft.insights/scheduledqueryrules":          ("module/monitor-scheduled-query",  "Baja",  "No"),
    "microsoft.insights/datacollectionrules":          ("module/data-collection-rule",     "Baja",  "No"),
    "microsoft.insights/datacollectionendpoints":      ("module/data-collection-endpoint", "Baja",  "No"),
    "microsoft.insights/workbooks":                    ("module/monitor-workbook",         "Baja",  "No"),
    "microsoft.alertsmanagement/prometheusrulegroups": ("module/prometheus-rule-group",    "Media", "No"),
    "microsoft.alertsmanagement/smartdetectoralertrules": ("module/smart-detector-alert",  "Baja",  "No"),
    "microsoft.operationalinsights/workspaces":        ("module/log-analytics-workspace",  "Alta",  "Si"),
    "microsoft.operationsmanagement/solutions":        ("module/log-analytics-solution",   "Baja",  "No"),
    "microsoft.monitor/accounts":                      ("module/monitor-account",          "Media", "Si"),
    # ── INTEGRATION ───────────────────────────────────────────────────────
    "microsoft.servicebus/namespaces":                 ("module/service-bus",              "Alta",  "Si"),
    "microsoft.relay/namespaces":                      ("module/relay-namespace",          "Media", "Si"),
    "microsoft.eventhub/namespaces":                   ("module/event-hub",                "Alta",  "Si"),
    "microsoft.eventgrid/systemtopics":                ("module/event-grid-topic",         "Media", "Si"),
    "microsoft.eventgrid/topics":                      ("module/event-grid-topic",         "Media", "Si"),
    "microsoft.logic/workflows":                       ("module/logic-app",                "Media", "Si"),
    "microsoft.apimanagement/service":                 ("module/api-management",           "Alta",  "Si"),
    "microsoft.communication/communicationservices":   ("module/communication-service",    "Media", "Si"),
    "microsoft.signalrservice/signalr":                ("module/signalr-service",          "Media", "Si"),
    "microsoft.signalrservice/webpubsub":              ("module/web-pubsub",               "Media", "Si"),
    # ── DEVCENTER ─────────────────────────────────────────────────────────
    "microsoft.devcenter/devcenters":                  ("module/dev-center",               "Baja",  "Si"),
    "microsoft.devcenter/networkconnections":          ("module/dev-center-network",       "Baja",  "Si"),
    "microsoft.devcenter/projects":                    ("module/dev-center-project",       "Baja",  "Si"),
}


def main():
    wb = openpyxl.load_workbook(EXCEL)
    ws = wb[SHEET]

    headers = [c.value for c in ws[1]]
    col = {h: i+1 for i, h in enumerate(headers) if h}

    updated = {"candidate_module": 0, "adoption_priority": 0, "requires_terraform_import": 0}

    for row in ws.iter_rows(min_row=2):
        rtype = (row[col["type"]-1].value or "").lower()
        if rtype not in TYPE_MAP:
            continue
        module, priority, tf_import = TYPE_MAP[rtype]

        # candidate_module — solo si vacío
        cell_mod = row[col["candidate_module"]-1]
        if not cell_mod.value:
            cell_mod.value = module
            updated["candidate_module"] += 1

        # adoption_priority — sobreescribir siempre (normalizar según tipo)
        cell_prio = row[col["adoption_priority"]-1]
        if cell_prio.value != priority:
            cell_prio.value = priority
            updated["adoption_priority"] += 1

        # requires_terraform_import — sobreescribir si es "Por confirmar" o vacío
        cell_tf = row[col["requires_terraform_import"]-1]
        if not cell_tf.value or cell_tf.value == "Por confirmar":
            cell_tf.value = tf_import
            updated["requires_terraform_import"] += 1

    wb.save(EXCEL)

    print(f"  candidate_module actualizado:          {updated['candidate_module']}")
    print(f"  adoption_priority actualizado:         {updated['adoption_priority']}")
    print(f"  requires_terraform_import actualizado: {updated['requires_terraform_import']}")
    print(f"\n✅ {EXCEL.name} guardado")


if __name__ == "__main__":
    main()

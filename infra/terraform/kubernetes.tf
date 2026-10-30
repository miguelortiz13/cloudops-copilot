# ---------------------------------------------------------------------------
# Kubernetes: el agente de cada clúster sube su foto a k8s-<nombre>/latest.json
# con una SAS que solo crea y escribe en ese contenedor (ni lee ni lista). El API
# la lee con su identidad. Rotar la clave de la cuenta revoca todas las SAS.
# ---------------------------------------------------------------------------
data "azurerm_storage_account_blob_container_sas" "k8s_agent" {
  for_each          = var.kubernetes_clusters
  connection_string = "DefaultEndpointsProtocol=https;AccountName=${module.storage.name};AccountKey=${module.storage.primary_access_key};EndpointSuffix=core.windows.net"
  container_name    = "k8s-${each.value}"
  https_only        = true
  start             = "2026-10-01"
  expiry            = var.kubernetes_agent_sas_expiry

  permissions {
    read   = false
    add    = false
    create = true
    write  = true
    delete = false
    list   = false
  }
}

resource "azurerm_role_assignment" "k8s_snapshot_reader" {
  count                = length(var.kubernetes_clusters) > 0 ? 1 : 0
  scope                = module.storage.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = module.api_identity.principal_id
}

# ---------------------------------------------------------------------------
# Avisos casi en vivo (app/collectors/k8s_watch.py): revisa las fotos cada 10
# minutos y avisa al webhook de lo nuevo y lo resuelto. No abre la base; su
# estado vive en el File Share. Solo existe con clústeres y webhook.
# Consumo: unos segundos de 0,25 vCPU por ejecución, dentro del cupo gratuito.
# ---------------------------------------------------------------------------
module "k8s_watch" {
  count  = length(var.kubernetes_clusters) > 0 && local.notify_enabled ? 1 : 0
  source = "git::https://github.com/miguelortiz13/terraform-modules-iac.git//modules/azure/container-app-job?ref=v0.3.0"

  name                         = "caj-${local.base}-k8s-watch"
  resource_group_name          = module.rg.name
  location                     = module.rg.location
  container_app_environment_id = module.cae.id
  tags                         = local.tags

  cron_expression            = var.kubernetes_watch_cron
  cpu                        = 0.25
  memory                     = "0.5Gi"
  replica_timeout_in_seconds = 300
  replica_retry_limit        = 0
  identity_ids               = [module.api_identity.id]

  image   = var.api_image
  command = ["python", "-m", "app.collectors.k8s_watch"]
  volumes = { (local.data_share) = local.data_mount_path }
  env = {
    AZURE_MANAGED_IDENTITY_CLIENT_ID = module.api_identity.client_id
    K8S_CLUSTERS                     = join(",", sort(var.kubernetes_clusters))
    K8S_SNAPSHOT_ACCOUNT             = module.storage.name
    DATA_DIR                         = local.data_mount_path
    APP_NAME                         = var.app_display_name
    FRONTEND_URL                     = module.web.url
  }

  secrets    = { "notify-webhook-url" = var.notify_webhook_url }
  secret_env = { NOTIFY_WEBHOOK_URL = "notify-webhook-url" }
}

# ---------------------------------------------------------------------------
# Incidentes: token con que Alertmanager (u otra fuente) envía alertas a
# /api/alerts/alertmanager (app/ai/incidentes.py). Rotarlo: terraform apply
# -replace=random_password.alerts_ingest y actualizar la fuente.
# ---------------------------------------------------------------------------
resource "random_password" "alerts_ingest" {
  length  = 40
  special = false
}

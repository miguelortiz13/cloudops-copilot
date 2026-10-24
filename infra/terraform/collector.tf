# ---------------------------------------------------------------------------
# Recolector diario: Container Apps Job programado (ADR 0007)
# ---------------------------------------------------------------------------
#
# Misma imagen y misma identidad que el API (solo lectura sobre Azure; en la
# base, lectura, escritura y DDL para aplicar migraciones). Corre una vez al
# dia: es la ventana que el cupo gratuito de Azure SQL admite
# (docs/plan/05-infraestructura.md). Consumo: unos 2 minutos de 0,5 vCPU al
# dia, dentro del cupo gratuito mensual de Container Apps.

locals {
  collector_env = {
    AZURE_MANAGED_IDENTITY_CLIENT_ID = module.api_identity.client_id
    AZURE_SUBSCRIPTION_ID            = var.subscription_id
    MANDATORY_TAGS                   = join(",", var.mandatory_tags)
    SHOWBACK_TAGS                    = join(",", var.showback_tags)
    TFSTATE_ACCOUNT                  = local.tfstate_sources
    DB_SERVER                        = module.sql.server_fqdn
    DB_NAME                          = module.sql.database_name
    # La precarga de costos es del API; el job consulta lo suyo.
    COST_WARM_ENABLED = "false"
    # Mismo File Share que el API: ahi deja las vistas precalculadas del panel
    # (app/readmodel), para que leerlas no despierte la base.
    DATA_DIR = local.data_mount_path
    # Titulo y enlace de los avisos (app/collectors/notify.py).
    APP_NAME            = var.app_display_name
    FRONTEND_URL        = module.web.url
    MONTHLY_BUDGETS_USD = join(",", [for nube, monto in var.monthly_budgets_usd : "${nube}=${monto}"])
    # Clústeres con agente: inventario y hallazgos desde sus fotos (kubernetes.tf).
    K8S_CLUSTERS         = join(",", sort(var.kubernetes_clusters))
    K8S_SNAPSHOT_ACCOUNT = module.storage.name
  }
  # Federación con AWS (aws.tf): rol a asumir y audiencia del token de Entra.
  aws_env = local.aws_enabled ? {
    AWS_ROLE_ARN       = module.aws_onboarding[0].role_arn
    AWS_ENTRA_AUDIENCE = azuread_application_identifier_uri.aws_federation[0].identifier_uri
    AWS_DEFAULT_REGION = var.aws_region
    # Vista de Resource Explorer: inventario de AWS (app/providers/aws).
    AWS_INVENTORY_VIEW_ARN = module.aws_onboarding[0].inventory_view_arn
    # Costos: tabla del export FOCUS en Athena (vacías si el export no se crea).
    AWS_COST_DATABASE  = try(module.aws_onboarding[0].cost_export.database, "")
    AWS_COST_TABLE     = try(module.aws_onboarding[0].cost_export.table, "")
    AWS_COST_WORKGROUP = try(module.aws_onboarding[0].cost_export.workgroup, "")
  } : {}
}

module "collector" {
  source = "git::https://github.com/miguelortiz13/terraform-modules-iac.git//modules/azure/container-app-job?ref=v0.3.0"

  name                         = "caj-${local.base}-collector"
  resource_group_name          = module.rg.name
  location                     = module.rg.location
  container_app_environment_id = module.cae.id
  tags                         = local.tags

  cron_expression            = var.collector_cron
  replica_timeout_in_seconds = 1800
  replica_retry_limit        = 1
  identity_ids               = [module.api_identity.id]

  image   = var.api_image
  command = ["python", "-m", "app.collectors.run"]
  volumes = { (local.data_share) = local.data_mount_path }
  env     = merge(local.collector_env, local.aws_env)

  # La URL del webhook es una credencial: va como secreto, no como variable.
  secrets    = local.notify_enabled ? { "notify-webhook-url" = var.notify_webhook_url } : {}
  secret_env = local.notify_enabled ? { NOTIFY_WEBHOOK_URL = "notify-webhook-url" } : {}
}

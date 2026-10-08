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
    AZURE_MANAGED_IDENTITY_CLIENT_ID = azurerm_user_assigned_identity.api.client_id
    AZURE_SUBSCRIPTION_ID            = var.subscription_id
    MANDATORY_TAGS                   = join(",", var.mandatory_tags)
    SHOWBACK_TAGS                    = join(",", var.showback_tags)
    TFSTATE_ACCOUNT                  = local.tfstate_sources
    DB_SERVER                        = azurerm_mssql_server.sql.fully_qualified_domain_name
    DB_NAME                          = azapi_resource.db.name
    # La precarga de costos es del API; el job consulta lo suyo.
    COST_WARM_ENABLED = "false"
    # Mismo File Share que el API: ahi deja las vistas precalculadas del panel
    # (app/readmodel), para que leerlas no despierte la base.
    DATA_DIR = local.data_mount_path
  }
}

resource "azurerm_container_app_job" "collector" {
  name                         = "caj-${local.base}-collector"
  resource_group_name          = azurerm_resource_group.rg.name
  location                     = azurerm_resource_group.rg.location
  container_app_environment_id = azurerm_container_app_environment.env.id
  replica_timeout_in_seconds   = 1800
  replica_retry_limit          = 1
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.api.id]
  }

  schedule_trigger_config {
    cron_expression          = var.collector_cron
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    volume {
      name         = "data"
      storage_type = "AzureFile"
      storage_name = azurerm_container_app_environment_storage.data.name
    }

    container {
      name    = "collector"
      image   = var.api_image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "-m", "app.collectors.run"]

      volume_mounts {
        name = "data"
        path = local.data_mount_path
      }

      dynamic "env" {
        for_each = local.collector_env
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  # La imagen la actualiza el workflow de CD junto con la del API.
  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }
}

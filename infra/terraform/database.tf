# ---------------------------------------------------------------------------
# Base de datos: Azure SQL Database con la oferta gratuita (ADR 0007)
# ---------------------------------------------------------------------------
#
# La oferta incluye cada mes 100.000 vCore-segundos de cómputo serverless y
# 32 GB de datos. Con `freeLimitExhaustionBehavior = AutoPause` la base se
# pausa al agotar el cupo hasta el mes siguiente en lugar de facturar el
# excedente: el costo queda en USD 0 y la plataforma degrada a consultas en
# vivo. El presupuesto de uso está en docs/plan/05-infraestructura.md.
#
# Autenticación solo con Entra ID: no hay usuario ni contraseña de SQL. El
# administrador es quien aplica Terraform; la identidad del API entra como
# usuario contenido (scripts/db-bootstrap.sh).

data "azuread_user" "sql_admin" {
  object_id = data.azuread_client_config.current.object_id
}

locals {
  # Los nombres de servidor SQL son globales: sufijo estable por suscripción y
  # región (un nombre usado en otra región queda reservado un tiempo).
  sql_server_name = "sql-${local.base}-${substr(sha1("${var.subscription_id}/${var.sql_location}"), 0, 6)}"
}

resource "azurerm_mssql_server" "sql" {
  name                          = local.sql_server_name
  resource_group_name           = azurerm_resource_group.rg.name
  location                      = var.sql_location
  version                       = "12.0"
  minimum_tls_version           = "1.2"
  public_network_access_enabled = true
  tags                          = local.tags

  azuread_administrator {
    login_username              = data.azuread_user.sql_admin.user_principal_name
    object_id                   = data.azuread_user.sql_admin.object_id
    azuread_authentication_only = true
  }
}

# Container Apps de consumo sale a Internet con IPs que no son fijas: la regla
# 0.0.0.0 admite solo tráfico originado dentro de Azure. El acceso sigue
# exigiendo un token de Entra ID de una identidad con usuario en la base.
resource "azurerm_mssql_firewall_rule" "azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_mssql_server.sql.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# azurerm no expone los parámetros de la oferta gratuita (useFreeLimit y
# freeLimitExhaustionBehavior): la base se declara con azapi.
resource "azapi_resource" "db" {
  type      = "Microsoft.Sql/servers/databases@2025-01-01"
  name      = "sqldb-${local.base}"
  parent_id = azurerm_mssql_server.sql.id
  location  = var.sql_location
  tags      = local.tags

  body = {
    sku = {
      name     = "GP_S_Gen5"
      tier     = "GeneralPurpose"
      family   = "Gen5"
      capacity = 1
    }
    properties = {
      useFreeLimit                = true
      freeLimitExhaustionBehavior = "AutoPause"
      # La oferta gratuita con AutoPause solo admite el retardo de pausa por
      # defecto (60 minutos sin conexiones); no se declara autoPauseDelay.
      minCapacity                      = 0.5
      maxSizeBytes                     = 34359738368
      zoneRedundant                    = false
      requestedBackupStorageRedundancy = "Local"
    }
  }

  response_export_values = ["properties.currentServiceObjectiveName", "properties.status"]
}

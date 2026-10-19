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

module "sql" {
  source = "git::https://github.com/miguelortiz13/terraform-modules-iac.git//modules/azure/mssql-serverless-free?ref=v0.3.0"

  server_name         = local.sql_server_name
  database_name       = "sqldb-${local.base}"
  resource_group_name = module.rg.name
  location            = var.sql_location
  tags                = local.tags

  entra_admin = {
    login_username = data.azuread_user.sql_admin.user_principal_name
    object_id      = data.azuread_user.sql_admin.object_id
  }
}

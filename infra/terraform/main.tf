terraform {
  required_version = ">= 1.5.0"

  # Configuracion parcial: los datos de la cuenta del estado se pasan en
  # `terraform init -backend-config=backend.hcl` (ver backend.hcl.example).
  backend "azurerm" {}

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.8"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.10"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.13"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
  # Los proveedores de recursos se registran aparte (scripts/bootstrap-state.sh):
  # registrar todos en cada plan exige permisos amplios y no aporta nada aqui.
  resource_provider_registrations = "none"
}

provider "azuread" {}

provider "azapi" {
  subscription_id = var.subscription_id
}

data "azurerm_client_config" "current" {}
data "azuread_client_config" "current" {}

locals {
  # Nombres derivados de un prefijo y el ambiente: cloudops-dev -> ca-cloudops-dev.
  base = "${var.name_prefix}-${var.environment}"
  # Las cuentas de almacenamiento solo admiten minusculas y digitos (3-24).
  storage_name = substr(replace("st${var.name_prefix}${var.environment}data", "/[^a-z0-9]/", ""), 0, 24)

  tags = merge(var.tags, {
    Environment = var.environment
    Project     = var.name_prefix
    ManagedBy   = "Terraform"
  })

  data_mount_path = "/data"
  data_share      = "cloudops-data"
  gemini_enabled  = nonsensitive(var.gemini_api_key != "")
  notify_enabled  = nonsensitive(var.notify_webhook_url != "")

  # Cuentas de estados de Terraform a escanear: "cuenta/contenedor".
  tfstate_sources = join(",", [for s in var.tfstate_sources : "${element(split("/", s.storage_account_id), 8)}/${s.container}"])
}

# Módulos estándar de terraform-modules-iac. Los nombres se conservan (no se usa
# el módulo naming) para no recrear lo que ya está desplegado; moved.tf traslada
# el estado a las direcciones nuevas.

# ---------------------------------------------------------------------------
# Grupo de recursos
# ---------------------------------------------------------------------------
module "rg" {
  source = "git::https://github.com/miguelortiz13/terraform-modules-iac.git//modules/azure/resource-group?ref=v0.3.0"

  name     = "rg-${local.base}"
  location = var.location
  tags     = local.tags
}

# ---------------------------------------------------------------------------
# Identidad de la plataforma: solo lectura, sin secretos
# ---------------------------------------------------------------------------
module "api_identity" {
  source = "git::https://github.com/miguelortiz13/terraform-modules-iac.git//modules/azure/user-assigned-identity?ref=v0.3.0"

  name                = "id-${local.base}"
  resource_group_name = module.rg.name
  location            = module.rg.location
  tags                = local.tags
}

# Los permisos de lectura se declaran aparte del módulo: sus claves salen de
# terraform.tfvars y son lo que la plataforma observa, no parte de la identidad.

# Reader sobre cada suscripcion observada: inventario, SecOps y costos con
# alcance de suscripcion.
resource "azurerm_role_assignment" "reader" {
  for_each             = toset(var.observed_subscription_ids)
  scope                = "/subscriptions/${each.value}"
  role_definition_name = "Reader"
  principal_id         = module.api_identity.principal_id
}

# Reader heredado por cada suscripción del grupo de administración, incluidas
# las que se creen después: la plataforma las descubre sola.
resource "azurerm_role_assignment" "reader_management_group" {
  for_each             = toset(var.observed_management_group_ids)
  scope                = "/providers/Microsoft.Management/managementGroups/${each.value}"
  role_definition_name = "Reader"
  principal_id         = module.api_identity.principal_id
}

# Lectura de los estados de Terraform para medir la cobertura real de IaC.
resource "azurerm_role_assignment" "tfstate_reader" {
  for_each             = { for s in var.tfstate_sources : s.storage_account_id => s }
  scope                = each.key
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = module.api_identity.principal_id
}

# ---------------------------------------------------------------------------
# Almacenamiento persistente (cache de costos, historico de KPIs, Excel)
# ---------------------------------------------------------------------------
module "storage" {
  source = "git::https://github.com/miguelortiz13/terraform-modules-iac.git//modules/azure/storage-account?ref=v0.3.0"

  name                = local.storage_name
  resource_group_name = module.rg.name
  location            = module.rg.location
  tags                = local.tags

  # Container Apps monta el File Share con la clave de la cuenta.
  shared_access_key_enabled = true
  file_shares               = { (local.data_share) = 1 }
  # Un contenedor por clúster de Kubernetes (kubernetes.tf).
  containers = [for c in var.kubernetes_clusters : "k8s-${c}"]
}

# ---------------------------------------------------------------------------
# API en Container Apps (consumo, escala a cero)
# ---------------------------------------------------------------------------
# Sin Log Analytics: los logs se consultan en vivo con
# `az containerapp logs show`. Conectar un workspace es opcional y tiene costo.
module "cae" {
  source = "git::https://github.com/miguelortiz13/terraform-modules-iac.git//modules/azure/container-app-environment?ref=v0.3.0"

  name                = "cae-${local.base}"
  resource_group_name = module.rg.name
  location            = module.rg.location
  tags                = local.tags

  storages            = { (local.data_share) = { account_name = module.storage.name, share_name = local.data_share } }
  storage_access_keys = { (local.data_share) = module.storage.primary_access_key }
}

module "api" {
  source = "git::https://github.com/miguelortiz13/terraform-modules-iac.git//modules/azure/container-app?ref=v0.3.0"

  name                         = "ca-${local.base}-api"
  resource_group_name          = module.rg.name
  container_app_environment_id = module.cae.id
  tags                         = local.tags

  # 0 replicas en reposo: sin trafico no hay costo. La primera peticion
  # tras un periodo inactivo tarda unos segundos en arrancar el contenedor.
  image        = var.api_image
  min_replicas = 0
  max_replicas = 1
  identity_ids = [module.api_identity.id]
  ingress      = { target_port = 8000 }
  volumes      = { (local.data_share) = local.data_mount_path }

  # Sin clave, el chat y el generador de IaC usan el motor de reglas.
  # Credenciales como secretos: la clave del modelo, el webhook (reportes de incidentes) y el
  # token con que Alertmanager se autentica en /api/alerts/alertmanager.
  secrets = merge(
    local.gemini_enabled ? { "gemini-api-key" = var.gemini_api_key } : {},
    local.notify_enabled ? { "notify-webhook-url" = var.notify_webhook_url } : {},
    { "alerts-ingest-token" = random_password.alerts_ingest.result },
  )
  secret_env = merge(
    local.gemini_enabled ? { GEMINI_API_KEY = "gemini-api-key" } : {},
    local.notify_enabled ? { NOTIFY_WEBHOOK_URL = "notify-webhook-url" } : {},
    { ALERTS_INGEST_TOKEN = "alerts-ingest-token" },
  )

  env = {
    AZURE_MANAGED_IDENTITY_CLIENT_ID = module.api_identity.client_id
    AZURE_SUBSCRIPTION_ID            = var.subscription_id
    APP_NAME                         = var.app_display_name
    ORG_NAME                         = var.org_name
    MANDATORY_TAGS                   = join(",", var.mandatory_tags)
    SHOWBACK_TAGS                    = join(",", var.showback_tags)
    DATA_DIR                         = local.data_mount_path
    FRONTEND_URL                     = module.web.url
    ALLOWED_ORIGINS                  = module.web.url
    TFSTATE_ACCOUNT                  = local.tfstate_sources
    AUTH_ENABLED                     = "true"
    AZURE_AD_TENANT_ID               = data.azurerm_client_config.current.tenant_id
    AZURE_AD_API_CLIENT_ID           = azuread_application.api.client_id
    # Las vistas precalculadas valen hasta que termine la siguiente
    # recoleccion: el API necesita saber a que hora corre (collector_cron).
    COLLECTOR_HOUR_UTC   = split(" ", var.collector_cron)[1]
    AUTHZ_GROUP_ADMIN    = azuread_group.role["Admin"].object_id
    AUTHZ_GROUP_OPERATOR = azuread_group.role["Operator"].object_id
    AUTHZ_GROUP_READER   = azuread_group.role["Reader"].object_id
    GEMINI_MODEL         = var.gemini_model
    DB_SERVER            = module.sql.server_fqdn
    DB_NAME              = module.sql.database_name
    # La cache de la vision general de costos la deja el recolector diario en
    # /data (paso costcache): el API no precarga al arrancar y la considera
    # vigente hasta la siguiente recoleccion (26 h).
    COST_WARM_ENABLED      = "false"
    COST_CACHE_TTL_SECONDS = "93600"
    # Presupuesto por nube: el reporte mensual descargado desde el panel lo muestra.
    MONTHLY_BUDGETS_USD = join(",", [for nube, monto in var.monthly_budgets_usd : "${nube}=${monto}"])
    # Fotos de los agentes de Kubernetes (kubernetes.tf).
    K8S_CLUSTERS         = join(",", sort(var.kubernetes_clusters))
    K8S_SNAPSHOT_ACCOUNT = module.storage.name
  }
}

# ---------------------------------------------------------------------------
# Panel (Static Web App gratuita)
# ---------------------------------------------------------------------------
module "web" {
  source = "git::https://github.com/miguelortiz13/terraform-modules-iac.git//modules/azure/static-web-app?ref=v0.3.0"

  name                = "stapp-${local.base}"
  resource_group_name = module.rg.name
  location            = var.static_web_app_location
  tags                = local.tags
}

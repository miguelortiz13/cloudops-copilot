terraform {
  required_version = ">= 1.5.0"

  # Configuracion parcial: los datos de la cuenta del estado se pasan en
  # `terraform init -backend-config=backend.hcl` (ver backend.hcl.example), asi
  # el codigo no queda atado a ninguna suscripcion concreta.
  backend "azurerm" {}

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
  tenant_id       = var.tenant_id
}

locals {
  # Nombres derivados de un prefijo y el ambiente: cloudops-dev -> app-cloudops-dev.
  base = "${var.name_prefix}-${var.environment}"
  # Las cuentas de almacenamiento solo admiten minusculas y digitos (3-24).
  storage_name = substr(replace("st${var.name_prefix}${var.environment}data", "/[^a-z0-9]/", ""), 0, 24)

  tags = merge(var.tags, {
    Environment = title(var.environment)
    Provisioner = "Terraform"
  })

  # Ruta donde el App Service monta el File Share; el backend la lee como DATA_DIR.
  data_mount_path = "/home/site/data"
}

# ---------------------------------------------------------------------------
# Grupo de recursos
# ---------------------------------------------------------------------------
resource "azurerm_resource_group" "rg" {
  name     = "rg-${local.base}"
  location = var.location
  tags     = local.tags
}

# ---------------------------------------------------------------------------
# Almacenamiento persistente (cache de costos, historico de KPIs, Excel)
# ---------------------------------------------------------------------------
resource "azurerm_storage_account" "data" {
  name                            = local.storage_name
  resource_group_name             = azurerm_resource_group.rg.name
  location                        = azurerm_resource_group.rg.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags                            = local.tags
}

resource "azurerm_storage_share" "data" {
  name                 = "cloudops-data"
  storage_account_name = azurerm_storage_account.data.name
  quota                = 5
}

# ---------------------------------------------------------------------------
# Backend (FastAPI en App Service Linux)
# ---------------------------------------------------------------------------
resource "azurerm_service_plan" "plan" {
  name                = "asp-${local.base}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  os_type             = "Linux"
  sku_name            = var.app_service_sku
  tags                = local.tags
}

resource "azurerm_linux_web_app" "api" {
  name                = "app-${local.base}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  service_plan_id     = azurerm_service_plan.plan.id
  https_only          = true
  tags                = local.tags

  site_config {
    application_stack {
      python_version = "3.12"
    }
    app_command_line = "uvicorn app.main:app --host 0.0.0.0 --port 8000"
    ftps_state       = "Disabled"
  }

  app_settings = {
    "SCM_DO_BUILD_DURING_DEPLOYMENT" = "true"
    "WEBSITES_PORT"                  = "8000"
    # Con SCM_DO_BUILD_DURING_DEPLOYMENT cada despliegue reinstala dependencias
    # (pandas y los SDK de Azure tardan minutos); el limite por defecto de 230 s
    # marca como fallido un arranque que termina bien poco despues.
    "WEBSITES_CONTAINER_START_TIME_LIMIT" = "1800"

    # Organizacion
    "APP_NAME"       = var.app_display_name
    "ORG_NAME"       = var.org_name
    "MANDATORY_TAGS" = join(",", var.mandatory_tags)
    "FRONTEND_URL"   = "https://${azurerm_static_web_app.web.default_host_name}"
    "DATA_DIR"       = local.data_mount_path

    # Lectura del tenant: Service Principal con rol Reader.
    "AZURE_TENANT_ID"            = var.tenant_id
    "AZURE_CLIENT_ID"            = var.bot_app_id
    "AZURE_CLIENT_SECRET"        = var.bot_app_password
    "AZURE_SUBSCRIPTION_ID"      = var.subscription_id
    "AZURE_READER_CLIENT_ID"     = var.reader_client_id
    "AZURE_READER_CLIENT_SECRET" = var.reader_client_secret

    "GEMINI_API_KEY" = var.gemini_api_key

    # CORS: solo el dominio del panel puede llamar al API.
    "ALLOWED_ORIGINS" = "https://${azurerm_static_web_app.web.default_host_name}"

    # Autenticacion con Entra ID. Con auth_enabled = false el API queda abierto
    # a quien conozca la URL; ver docs/security.md.
    "AUTH_ENABLED"           = tostring(var.auth_enabled)
    "AZURE_AD_TENANT_ID"     = var.tenant_id
    "AZURE_AD_API_CLIENT_ID" = var.api_client_id

    # El webhook de Teams lo invoca Bot Framework, no una persona: se protege
    # validando el JWT que firma. La audiencia esperada es el App Id del bot.
    "BOT_AUTH_ENABLED" = "true"
    "MICROSOFT_APP_ID" = var.bot_app_id

    # Cobertura real de IaC (lectura de estados de Terraform). Opcional.
    "TFSTATE_ACCOUNT"   = var.tfstate_account_to_scan
    "TFSTATE_CONTAINER" = var.tfstate_container_to_scan

    # Agente SRE de Kubernetes. Opcional.
    "K8S_CLUSTER_NAME"    = var.k8s_cluster_name
    "K8S_RESOURCE_GROUP"  = var.k8s_resource_group
    "K8S_SUBSCRIPTION_ID" = var.k8s_subscription_id
  }

  storage_account {
    name         = "cloudops-data"
    type         = "AzureFiles"
    account_name = azurerm_storage_account.data.name
    access_key   = azurerm_storage_account.data.primary_access_key
    share_name   = azurerm_storage_share.data.name
    mount_path   = local.data_mount_path
  }
}

# ---------------------------------------------------------------------------
# Frontend (Static Web App)
# ---------------------------------------------------------------------------
resource "azurerm_static_web_app" "web" {
  name                = "stapp-${local.base}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.static_web_app_location
  sku_tier            = "Free"
  sku_size            = "Free"
  tags                = local.tags
}

# ---------------------------------------------------------------------------
# Bot de Microsoft Teams (opcional)
# ---------------------------------------------------------------------------
resource "azurerm_bot_service_azure_bot" "bot" {
  count                   = var.enable_teams_bot ? 1 : 0
  name                    = "bot-${local.base}"
  resource_group_name     = azurerm_resource_group.rg.name
  location                = "global"
  sku                     = "F0"
  microsoft_app_id        = var.bot_app_id
  microsoft_app_tenant_id = var.tenant_id
  microsoft_app_type      = "SingleTenant"
  endpoint                = "https://${azurerm_linux_web_app.api.default_hostname}/api/teams/webhook"
  tags                    = local.tags
}

resource "azurerm_bot_channel_ms_teams" "teams" {
  count               = var.enable_teams_bot ? 1 : 0
  bot_name            = azurerm_bot_service_azure_bot.bot[0].name
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_bot_service_azure_bot.bot[0].location
}

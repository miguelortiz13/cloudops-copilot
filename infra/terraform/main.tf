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
  gemini_enabled  = nonsensitive(var.gemini_api_key != "")

  # Cuentas de estados de Terraform a escanear: "cuenta/contenedor".
  tfstate_sources = join(",", [for s in var.tfstate_sources : "${element(split("/", s.storage_account_id), 8)}/${s.container}"])
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
# Identidad de la plataforma: solo lectura, sin secretos
# ---------------------------------------------------------------------------
resource "azurerm_user_assigned_identity" "api" {
  name                = "id-${local.base}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  tags                = local.tags
}

# Reader sobre cada suscripcion observada: inventario, SecOps y costos con
# alcance de suscripcion.
resource "azurerm_role_assignment" "reader" {
  for_each             = toset(var.observed_subscription_ids)
  scope                = "/subscriptions/${each.value}"
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
}

# Lectura de los estados de Terraform para medir la cobertura real de IaC.
resource "azurerm_role_assignment" "tfstate_reader" {
  for_each             = { for s in var.tfstate_sources : s.storage_account_id => s }
  scope                = each.key
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
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
  name               = "cloudops-data"
  storage_account_id = azurerm_storage_account.data.id
  quota              = 1
}

# ---------------------------------------------------------------------------
# API en Container Apps (consumo, escala a cero)
# ---------------------------------------------------------------------------
# Sin Log Analytics: los logs se consultan en vivo con
# `az containerapp logs show`. Conectar un workspace es opcional y tiene costo.
resource "azurerm_container_app_environment" "env" {
  name                = "cae-${local.base}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  tags                = local.tags
}

resource "azurerm_container_app_environment_storage" "data" {
  name                         = "cloudops-data"
  container_app_environment_id = azurerm_container_app_environment.env.id
  account_name                 = azurerm_storage_account.data.name
  share_name                   = azurerm_storage_share.data.name
  access_key                   = azurerm_storage_account.data.primary_access_key
  access_mode                  = "ReadWrite"
}

resource "azurerm_container_app" "api" {
  name                         = "ca-${local.base}-api"
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.env.id
  revision_mode                = "Single"
  # Cada merge a main crea una revisión; basta con unas pocas para volver atrás.
  max_inactive_revisions = 5
  tags                   = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.api.id]
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    # 0 replicas en reposo: sin trafico no hay costo. La primera peticion
    # tras un periodo inactivo tarda unos segundos en arrancar el contenedor.
    min_replicas = 0
    max_replicas = 1

    volume {
      name         = "data"
      storage_type = "AzureFile"
      storage_name = azurerm_container_app_environment_storage.data.name
    }

    container {
      name   = "api"
      image  = var.api_image
      cpu    = 0.5
      memory = "1Gi"

      volume_mounts {
        name = "data"
        path = local.data_mount_path
      }

      env {
        name  = "AZURE_MANAGED_IDENTITY_CLIENT_ID"
        value = azurerm_user_assigned_identity.api.client_id
      }
      env {
        name  = "AZURE_SUBSCRIPTION_ID"
        value = var.subscription_id
      }
      env {
        name  = "APP_NAME"
        value = var.app_display_name
      }
      env {
        name  = "ORG_NAME"
        value = var.org_name
      }
      env {
        name  = "MANDATORY_TAGS"
        value = join(",", var.mandatory_tags)
      }
      env {
        name  = "SHOWBACK_TAGS"
        value = join(",", var.showback_tags)
      }
      env {
        name  = "DATA_DIR"
        value = local.data_mount_path
      }
      env {
        name  = "FRONTEND_URL"
        value = "https://${azurerm_static_web_app.web.default_host_name}"
      }
      env {
        name  = "ALLOWED_ORIGINS"
        value = "https://${azurerm_static_web_app.web.default_host_name}"
      }
      env {
        name  = "TFSTATE_ACCOUNT"
        value = local.tfstate_sources
      }
      env {
        name  = "AUTH_ENABLED"
        value = "true"
      }
      env {
        name  = "AZURE_AD_TENANT_ID"
        value = data.azurerm_client_config.current.tenant_id
      }
      env {
        name  = "AZURE_AD_API_CLIENT_ID"
        value = azuread_application.api.client_id
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      # Sin clave, el chat y el generador de IaC usan el motor de reglas.
      dynamic "env" {
        for_each = local.gemini_enabled ? [1] : []
        content {
          name        = "GEMINI_API_KEY"
          secret_name = "gemini-api-key"
        }
      }
      # La precarga de costos corre mientras haya una replica viva; con escala
      # a cero se apoya en la cache persistida en /data.
      env {
        name  = "DB_SERVER"
        value = azurerm_mssql_server.sql.fully_qualified_domain_name
      }
      env {
        name  = "DB_NAME"
        value = azapi_resource.db.name
      }
      env {
        name  = "COST_WARM_INITIAL_DELAY_SECONDS"
        value = "5"
      }
    }
  }

  dynamic "secret" {
    for_each = local.gemini_enabled ? [1] : []
    content {
      name  = "gemini-api-key"
      value = var.gemini_api_key
    }
  }

  # La imagen la actualiza el despliegue continuo (az containerapp update).
  # Sin esto, cada `terraform apply` volvería a la imagen de terraform.tfvars.
  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }
}

# ---------------------------------------------------------------------------
# Panel (Static Web App gratuita)
# ---------------------------------------------------------------------------
resource "azurerm_static_web_app" "web" {
  name                = "stapp-${local.base}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.static_web_app_location
  sku_tier            = "Free"
  sku_size            = "Free"
  tags                = local.tags

  # Azure registra el repositorio al publicar con el token de despliegue (CD);
  # Terraform no administra ese vínculo.
  lifecycle {
    ignore_changes = [repository_url, repository_branch]
  }
}

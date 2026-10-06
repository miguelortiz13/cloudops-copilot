# ---------------------------------------------------------------------------
# Autenticacion con Microsoft Entra ID
# ---------------------------------------------------------------------------
#
# Dos registros de aplicacion:
# - API: expone el scope `access_as_user`; el backend valida que los tokens
#   vayan dirigidos a el (audiencia = su client id).
# - Panel (SPA): inicia sesion con MSAL y pide tokens para ese scope. Esta
#   preautorizado en el API, asi que no aparece pantalla de consentimiento.
#
# El acceso queda restringido a los usuarios asignados (por defecto, quien
# ejecuta Terraform): el resto del tenant recibe un error al iniciar sesion.

resource "random_uuid" "scope_access_as_user" {}

resource "azuread_application" "api" {
  display_name     = "${var.app_display_name} API (${var.environment})"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azuread_client_config.current.object_id]

  # La URI la gestiona azuread_application_identifier_uri (necesita el client
  # id, que solo existe despues de crear la app). Sin esto, cada apply la borra.
  lifecycle {
    ignore_changes = [identifier_uris]
  }

  api {
    # Tokens v2: la audiencia es el client id del API.
    requested_access_token_version = 2

    oauth2_permission_scope {
      id                         = random_uuid.scope_access_as_user.result
      value                      = "access_as_user"
      type                       = "User"
      admin_consent_display_name = "Usar ${var.app_display_name}"
      admin_consent_description  = "Permite al panel llamar al API en nombre del usuario."
      user_consent_display_name  = "Usar ${var.app_display_name}"
      user_consent_description   = "Permite al panel llamar al API en tu nombre."
      enabled                    = true
    }
  }
}

resource "azuread_application_identifier_uri" "api" {
  application_id = azuread_application.api.id
  identifier_uri = "api://${azuread_application.api.client_id}"
}

resource "azuread_service_principal" "api" {
  client_id = azuread_application.api.client_id
  # Solo los usuarios asignados obtienen tokens para el API, venga la peticion
  # del panel o de la CLI.
  app_role_assignment_required = true
  owners                       = [data.azuread_client_config.current.object_id]
}

resource "azuread_app_role_assignment" "api_users" {
  for_each            = toset(local.allowed_users)
  app_role_id         = "00000000-0000-0000-0000-000000000000"
  principal_object_id = each.value
  resource_object_id  = azuread_service_principal.api.object_id
}

# Azure CLI preautorizada: permite `az account get-access-token --scope ...`
# para pruebas y scripts (scripts/smoke-test.sh), limitada a los usuarios
# asignados arriba.
resource "azuread_application_pre_authorized" "azure_cli" {
  count                = var.allow_azure_cli ? 1 : 0
  application_id       = azuread_application.api.id
  authorized_client_id = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
  permission_ids       = [random_uuid.scope_access_as_user.result]
}

locals {
  allowed_users = coalescelist(var.allowed_user_object_ids, [data.azuread_client_config.current.object_id])
}

resource "azuread_application" "spa" {
  display_name     = "${var.app_display_name} (${var.environment})"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azuread_client_config.current.object_id]

  single_page_application {
    redirect_uris = concat(
      # Entra ID exige la barra final cuando no hay ruta; el panel usa la
      # misma forma (frontend/src/auth.ts).
      ["https://${azurerm_static_web_app.web.default_host_name}/"],
      var.local_redirect_uris,
    )
  }

  required_resource_access {
    resource_app_id = azuread_application.api.client_id
    resource_access {
      id   = random_uuid.scope_access_as_user.result
      type = "Scope"
    }
  }
}

resource "azuread_application_pre_authorized" "spa" {
  application_id       = azuread_application.api.id
  authorized_client_id = azuread_application.spa.client_id
  permission_ids       = [random_uuid.scope_access_as_user.result]
}

resource "azuread_service_principal" "spa" {
  client_id                    = azuread_application.spa.client_id
  app_role_assignment_required = true
  owners                       = [data.azuread_client_config.current.object_id]
}

# Usuarios con acceso al panel (rol por defecto de la aplicacion).
resource "azuread_app_role_assignment" "spa_users" {
  for_each            = toset(local.allowed_users)
  app_role_id         = "00000000-0000-0000-0000-000000000000"
  principal_object_id = each.value
  resource_object_id  = azuread_service_principal.spa.object_id
}

# ---------------------------------------------------------------------------
# AWS: federación de la identidad administrada, sin llaves (fase 2)
# ---------------------------------------------------------------------------
#
# La identidad administrada pide a Entra ID un token para el registro
# "federación AWS" y lo cambia en AWS STS por credenciales temporales del rol
# de lectura (AssumeRoleWithWebIdentity). Ver docs/plan/03-multicloud.md.
#
# Todo se crea solo si `aws_account_id` tiene valor. El apply necesita una
# sesión de AWS con permisos de IAM: AWS_PROFILE=<perfil SSO> terraform apply.

locals {
  aws_enabled = var.aws_account_id != ""
  # Tokens v1: emisor sts.windows.net y `aud` = URI del registro. Con tokens v2
  # AWS toma como audiencia el claim `azp` (el client id de la identidad, no el
  # del registro) y rechaza el token: probado en la fase 2, paso 1.
  entra_issuer = "sts.windows.net/${data.azuread_client_config.current.tenant_id}/"
  aws_audience = local.aws_enabled ? "api://${azuread_application.aws_federation[0].client_id}" : ""
}

provider "aws" {
  region = var.aws_region
  # Evita aplicar sobre otra cuenta si el perfil activo no es el esperado.
  allowed_account_ids = local.aws_enabled ? [var.aws_account_id] : null
}

resource "random_uuid" "aws_assume_role" {
  count = local.aws_enabled ? 1 : 0
}

# Audiencia de los tokens que acepta AWS. Exige asignación: solo la identidad
# de la plataforma puede pedir tokens para ella (la condición `sub` del rol es
# el segundo candado).
resource "azuread_application" "aws_federation" {
  count            = local.aws_enabled ? 1 : 0
  display_name     = "${var.app_display_name} federación AWS (${var.environment})"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azuread_client_config.current.object_id]

  # Tokens v1 (ver locals). La URI la gestiona azuread_application_identifier_uri.
  api {
    requested_access_token_version = 1
  }

  lifecycle {
    ignore_changes = [identifier_uris]
  }

  app_role {
    allowed_member_types = ["Application"]
    description          = "Puede cambiar su token por credenciales de AWS de solo lectura."
    display_name         = "Asumir rol de AWS"
    enabled              = true
    id                   = random_uuid.aws_assume_role[0].result
    value                = "AWS.AssumeRole"
  }
}

resource "azuread_application_identifier_uri" "aws_federation" {
  count          = local.aws_enabled ? 1 : 0
  application_id = azuread_application.aws_federation[0].id
  identifier_uri = local.aws_audience
}

resource "azuread_service_principal" "aws_federation" {
  count                        = local.aws_enabled ? 1 : 0
  client_id                    = azuread_application.aws_federation[0].client_id
  app_role_assignment_required = true
  owners                       = [data.azuread_client_config.current.object_id]
}

resource "azuread_app_role_assignment" "aws_federation" {
  count               = local.aws_enabled ? 1 : 0
  app_role_id         = random_uuid.aws_assume_role[0].result
  principal_object_id = azurerm_user_assigned_identity.api.principal_id
  resource_object_id  = azuread_service_principal.aws_federation[0].object_id
}

# Lo de AWS (OIDC, rol hub, inventario, costos) vive en el módulo, que una
# organización puede aplicar por su cuenta: infra/modules/aws-onboarding.
module "aws_onboarding" {
  source = "../modules/aws-onboarding"
  count  = local.aws_enabled ? 1 : 0

  name                = local.base
  oidc_issuer         = local.entra_issuer
  audience            = azuread_application_identifier_uri.aws_federation[0].identifier_uri
  principal_object_id = azurerm_user_assigned_identity.api.principal_id
  tags                = local.tags
}

# Paso 1 creó estos recursos en la raíz.
moved {
  from = aws_iam_openid_connect_provider.entra[0]
  to   = module.aws_onboarding[0].aws_iam_openid_connect_provider.entra
}

moved {
  from = aws_iam_role.reader[0]
  to   = module.aws_onboarding[0].aws_iam_role.hub
}

moved {
  from = aws_iam_role_policy_attachment.reader["SecurityAudit"]
  to   = module.aws_onboarding[0].aws_iam_role_policy_attachment.hub["SecurityAudit"]
}

moved {
  from = aws_iam_role_policy_attachment.reader["job-function/ViewOnlyAccess"]
  to   = module.aws_onboarding[0].aws_iam_role_policy_attachment.hub["job-function/ViewOnlyAccess"]
}

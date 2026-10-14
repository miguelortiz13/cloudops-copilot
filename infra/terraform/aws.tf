# ---------------------------------------------------------------------------
# AWS: federación de la identidad administrada, sin llaves (fase 2, paso 1)
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

resource "aws_iam_openid_connect_provider" "entra" {
  count          = local.aws_enabled ? 1 : 0
  url            = "https://${local.entra_issuer}"
  client_id_list = [azuread_application_identifier_uri.aws_federation[0].identifier_uri]
  tags           = local.tags
}

resource "aws_iam_role" "reader" {
  count                = local.aws_enabled ? 1 : 0
  name                 = "${local.base}-reader"
  description          = "Solo lectura de metadatos para ${var.app_display_name}; lo asume la identidad administrada de Azure por OIDC."
  max_session_duration = 3600
  tags                 = local.tags

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.entra[0].arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.entra_issuer}:aud" = azuread_application_identifier_uri.aws_federation[0].identifier_uri
          # Obligatoria: sin ella cualquier aplicación del tenant asumiría el rol.
          "${local.entra_issuer}:sub" = azurerm_user_assigned_identity.api.principal_id
        }
      }
    }]
  })
}

# Configuración y metadatos, sin leer datos: ReadOnlyAccess no sirve porque
# permite s3:GetObject y similares (docs/plan/03-multicloud.md).
resource "aws_iam_role_policy_attachment" "reader" {
  for_each   = local.aws_enabled ? toset(["SecurityAudit", "job-function/ViewOnlyAccess"]) : toset([])
  role       = aws_iam_role.reader[0].name
  policy_arn = "arn:aws:iam::aws:policy/${each.value}"
}

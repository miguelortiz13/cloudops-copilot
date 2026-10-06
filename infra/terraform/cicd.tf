# ---------------------------------------------------------------------------
# Despliegue continuo desde GitHub Actions, sin secretos
# ---------------------------------------------------------------------------
#
# GitHub Actions obtiene un token OIDC por ejecución y lo cambia por uno de
# Azure mediante una credencial federada: no hay client secret que guardar ni
# rotar. La credencial solo se acepta para el ambiente `dev` de este
# repositorio.
#
# Permiso mínimo: Contributor sobre el grupo de recursos de la plataforma, que
# basta para publicar una nueva imagen en la Container App y el panel en la
# Static Web App. No puede asignar roles ni tocar las suscripciones observadas:
# los cambios de infraestructura se siguen aplicando con `terraform apply`.

resource "azurerm_user_assigned_identity" "deploy" {
  name                = "id-${local.base}-deploy"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  tags                = local.tags
}

resource "azurerm_federated_identity_credential" "github" {
  name                = "github-${var.environment}"
  resource_group_name = azurerm_resource_group.rg.name
  parent_id           = azurerm_user_assigned_identity.deploy.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = "repo:${var.github_repository}:environment:${var.environment}"
}

resource "azurerm_role_assignment" "deploy" {
  scope                = azurerm_resource_group.rg.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
}

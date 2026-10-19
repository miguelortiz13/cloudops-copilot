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

module "deploy_identity" {
  source = "git::https://github.com/miguelortiz13/terraform-modules-iac.git//modules/azure/user-assigned-identity?ref=v0.3.0"

  name                = "id-${local.base}-deploy"
  resource_group_name = module.rg.name
  location            = module.rg.location
  tags                = local.tags

  role_assignments = {
    rg = { scope = module.rg.id, role_definition_name = "Contributor" }
  }

  federated_credentials = {
    "github-${var.environment}" = { subject = "repo:${var.github_repository}:environment:${var.environment}" }
  }
}

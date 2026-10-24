output "resource_group_name" {
  description = "Grupo de recursos de la plataforma."
  value       = module.rg.name
}

output "api_url" {
  description = "URL publica del API."
  value       = module.api.url
}

output "api_container_app_name" {
  description = "Nombre de la Container App del API."
  value       = module.api.name
}

output "frontend_url" {
  description = "URL publica del panel."
  value       = module.web.url
}

output "static_web_app_api_key" {
  description = "Token de despliegue de la Static Web App."
  value       = module.web.api_key
  sensitive   = true
}

output "tenant_id" {
  description = "Tenant de Entra ID."
  value       = data.azurerm_client_config.current.tenant_id
}

output "spa_client_id" {
  description = "Client id del panel (VITE_AZURE_AD_CLIENT_ID)."
  value       = azuread_application.spa.client_id
}

output "api_scope" {
  description = "Scope que pide el panel (VITE_API_SCOPE)."
  value       = "api://${azuread_application.api.client_id}/access_as_user"
}

output "identity_principal_id" {
  description = "Principal de la identidad administrada de la plataforma."
  value       = module.api_identity.principal_id
}

output "deploy_client_id" {
  description = "Client id de la identidad de despliegue (secreto AZURE_CLIENT_ID del ambiente de GitHub)."
  value       = module.deploy_identity.client_id
}

output "sql_server_fqdn" {
  description = "Servidor de Azure SQL (autenticación solo con Entra ID)."
  value       = module.sql.server_fqdn
}

output "sql_database_name" {
  value = module.sql.database_name
}

output "api_identity_name" {
  description = "Identidad administrada del API; entra a la base como usuario contenido (scripts/db-bootstrap.sh)."
  value       = "id-${local.base}"
}

output "collector_job_name" {
  value = module.collector.name
}

output "role_groups" {
  description = "Grupos de seguridad de Entra ID por rol."
  value       = { for k, g in azuread_group.role : k => { name = g.display_name, object_id = g.object_id } }
}

output "aws_reader_role_arn" {
  description = "Rol de AWS que asume la identidad administrada (vacío sin AWS)."
  value       = local.aws_enabled ? module.aws_onboarding[0].role_arn : null
}

output "kubernetes_agent_upload_urls" {
  description = "URL de subida de cada clúster (contenedor + SAS de solo escritura) para el secret del agente."
  value       = { for c in var.kubernetes_clusters : c => "${module.storage.primary_blob_endpoint}k8s-${c}${data.azurerm_storage_account_blob_container_sas.k8s_agent[c].sas}" }
  sensitive   = true
}

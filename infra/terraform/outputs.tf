output "resource_group_name" {
  description = "Grupo de recursos de la plataforma."
  value       = azurerm_resource_group.rg.name
}

output "api_url" {
  description = "URL publica del API."
  value       = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "api_container_app_name" {
  description = "Nombre de la Container App del API."
  value       = azurerm_container_app.api.name
}

output "frontend_url" {
  description = "URL publica del panel."
  value       = "https://${azurerm_static_web_app.web.default_host_name}"
}

output "static_web_app_api_key" {
  description = "Token de despliegue de la Static Web App."
  value       = azurerm_static_web_app.web.api_key
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
  value       = azurerm_user_assigned_identity.api.principal_id
}

output "deploy_client_id" {
  description = "Client id de la identidad de despliegue (secreto AZURE_CLIENT_ID del ambiente de GitHub)."
  value       = azurerm_user_assigned_identity.deploy.client_id
}

output "sql_server_fqdn" {
  description = "Servidor de Azure SQL (autenticación solo con Entra ID)."
  value       = azurerm_mssql_server.sql.fully_qualified_domain_name
}

output "sql_database_name" {
  value = azapi_resource.db.name
}

output "api_identity_name" {
  description = "Identidad administrada del API; entra a la base como usuario contenido (scripts/db-bootstrap.sh)."
  value       = azurerm_user_assigned_identity.api.name
}

output "collector_job_name" {
  value = azurerm_container_app_job.collector.name
}

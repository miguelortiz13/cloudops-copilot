output "resource_group_name" {
  description = "Grupo de recursos de la plataforma."
  value       = azurerm_resource_group.rg.name
}

output "api_app_name" {
  description = "Nombre del App Service del backend (lo usa scripts/deploy.sh)."
  value       = azurerm_linux_web_app.api.name
}

output "api_url" {
  description = "URL publica del backend."
  value       = "https://${azurerm_linux_web_app.api.default_hostname}"
}

output "static_web_app_name" {
  description = "Nombre de la Static Web App del panel (lo usa scripts/deploy.sh)."
  value       = azurerm_static_web_app.web.name
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

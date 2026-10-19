# Migración a los módulos de terraform-modules-iac (v0.3.0): mueve el estado de
# los recursos ya desplegados a sus nuevas direcciones, sin recrearlos. Tras el
# primer apply estos bloques no hacen nada; se pueden borrar más adelante.

moved {
  from = azurerm_resource_group.rg
  to   = module.rg.azurerm_resource_group.this
}

moved {
  from = azurerm_user_assigned_identity.api
  to   = module.api_identity.azurerm_user_assigned_identity.this
}

moved {
  from = azurerm_user_assigned_identity.deploy
  to   = module.deploy_identity.azurerm_user_assigned_identity.this
}

moved {
  from = azurerm_role_assignment.deploy
  to   = module.deploy_identity.azurerm_role_assignment.this["rg"]
}

# La clave es el nombre de la credencial (github-<environment>); este proyecto
# solo despliega el ambiente dev.
moved {
  from = azurerm_federated_identity_credential.github
  to   = module.deploy_identity.azurerm_federated_identity_credential.this["github-dev"]
}

moved {
  from = azurerm_storage_account.data
  to   = module.storage.azurerm_storage_account.this
}

moved {
  from = azurerm_storage_share.data
  to   = module.storage.azurerm_storage_share.this["cloudops-data"]
}

moved {
  from = azurerm_container_app_environment.env
  to   = module.cae.azurerm_container_app_environment.this
}

moved {
  from = azurerm_container_app_environment_storage.data
  to   = module.cae.azurerm_container_app_environment_storage.this["cloudops-data"]
}

moved {
  from = azurerm_container_app.api
  to   = module.api.azurerm_container_app.this
}

moved {
  from = azurerm_container_app_job.collector
  to   = module.collector.azurerm_container_app_job.this
}

moved {
  from = azurerm_static_web_app.web
  to   = module.web.azurerm_static_web_app.this
}

moved {
  from = azurerm_mssql_server.sql
  to   = module.sql.azurerm_mssql_server.this
}

moved {
  from = azurerm_mssql_firewall_rule.azure_services
  to   = module.sql.azurerm_mssql_firewall_rule.azure_services[0]
}

moved {
  from = azapi_resource.db
  to   = module.sql.azapi_resource.database
}

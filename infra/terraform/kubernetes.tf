# ---------------------------------------------------------------------------
# Kubernetes: el agente de cada clúster sube su foto a k8s-<nombre>/latest.json
# con una SAS que solo crea y escribe en ese contenedor (ni lee ni lista). El API
# la lee con su identidad. Rotar la clave de la cuenta revoca todas las SAS.
# ---------------------------------------------------------------------------
data "azurerm_storage_account_blob_container_sas" "k8s_agent" {
  for_each          = var.kubernetes_clusters
  connection_string = "DefaultEndpointsProtocol=https;AccountName=${module.storage.name};AccountKey=${module.storage.primary_access_key};EndpointSuffix=core.windows.net"
  container_name    = "k8s-${each.value}"
  https_only        = true
  start             = "2026-10-01"
  expiry            = var.kubernetes_agent_sas_expiry

  permissions {
    read   = false
    add    = false
    create = true
    write  = true
    delete = false
    list   = false
  }
}

resource "azurerm_role_assignment" "k8s_snapshot_reader" {
  count                = length(var.kubernetes_clusters) > 0 ? 1 : 0
  scope                = module.storage.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = module.api_identity.principal_id
}

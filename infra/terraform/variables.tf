# ---------------------------------------------------------------------------
# Destino del despliegue
# ---------------------------------------------------------------------------
variable "subscription_id" {
  description = "Suscripcion de Azure donde se despliega la plataforma."
  type        = string
}

variable "tenant_id" {
  description = "Tenant de Microsoft Entra ID."
  type        = string
}

variable "location" {
  description = "Region de Azure para los recursos."
  type        = string
  default     = "eastus2"
}

variable "static_web_app_location" {
  description = "Region de la Static Web App (no todas las regiones la ofrecen)."
  type        = string
  default     = "eastus2"
}

variable "name_prefix" {
  description = "Prefijo de los nombres de recursos (solo minusculas, digitos y guiones)."
  type        = string
  default     = "cloudops"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,16}$", var.name_prefix))
    error_message = "name_prefix debe tener 3-16 caracteres en minusculas, digitos o guiones."
  }
}

variable "environment" {
  description = "Ambiente (dev, qa, prod)."
  type        = string
  default     = "dev"
}

variable "app_service_sku" {
  description = "SKU del App Service Plan. B1 basta para un equipo pequeno."
  type        = string
  default     = "B1"
}

variable "tags" {
  description = "Tags comunes de los recursos de la plataforma."
  type        = map(string)
  default = {
    Product = "CloudOpsCopilot"
    Suite   = "Platform"
  }
}

# ---------------------------------------------------------------------------
# Organizacion que usa la plataforma
# ---------------------------------------------------------------------------
variable "app_display_name" {
  description = "Nombre visible de la plataforma."
  type        = string
  default     = "CloudOps Copilot"
}

variable "org_name" {
  description = "Nombre de la organizacion con el que se presentan los agentes."
  type        = string
  default     = "tu organización"
}

variable "mandatory_tags" {
  description = "Tags obligatorias que la plataforma evalua en el inventario."
  type        = list(string)
  default     = ["Customer", "Tenant", "Platform", "Product", "Suite", "Environment"]
}

# ---------------------------------------------------------------------------
# Identidades
# ---------------------------------------------------------------------------
variable "bot_app_id" {
  description = "Application (client) ID del registro de aplicacion del bot / API."
  type        = string
}

variable "bot_app_password" {
  description = "Client secret del registro del bot."
  type        = string
  sensitive   = true
}

variable "reader_client_id" {
  description = "Client ID del Service Principal con rol Reader sobre el tenant (opcional; si se omite se usa bot_app_id)."
  type        = string
  default     = ""
}

variable "reader_client_secret" {
  description = "Secret del Service Principal lector."
  type        = string
  default     = ""
  sensitive   = true
}

variable "gemini_api_key" {
  description = "API key de Google Gemini. Vacia = modo local basado en reglas."
  type        = string
  default     = ""
  sensitive   = true
}

variable "auth_enabled" {
  description = "Exige token de Microsoft Entra ID en el API. Requiere api_client_id."
  type        = bool
  default     = false
}

variable "api_client_id" {
  description = "Application (client) ID del App Registration que representa al API."
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Modulos opcionales
# ---------------------------------------------------------------------------
variable "enable_teams_bot" {
  description = "Crea el Azure Bot y el canal de Teams."
  type        = bool
  default     = true
}

variable "tfstate_account_to_scan" {
  description = "Cuenta de almacenamiento con los estados de Terraform de la organizacion, para medir la cobertura real de IaC. Vacia = desactivado."
  type        = string
  default     = ""
}

variable "tfstate_container_to_scan" {
  description = "Contenedor de esos estados."
  type        = string
  default     = "tfstate"
}

variable "k8s_cluster_name" {
  description = "Cluster AKS que diagnostica el Agente SRE (opcional)."
  type        = string
  default     = ""
}

variable "k8s_resource_group" {
  description = "Grupo de recursos del cluster AKS."
  type        = string
  default     = ""
}

variable "k8s_subscription_id" {
  description = "Suscripcion del cluster AKS."
  type        = string
  default     = ""
}

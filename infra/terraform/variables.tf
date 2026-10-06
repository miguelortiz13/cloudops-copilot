# ---------------------------------------------------------------------------
# Destino del despliegue
# ---------------------------------------------------------------------------
variable "subscription_id" {
  description = "Suscripcion de Azure donde se despliega la plataforma."
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
  description = "Prefijo de los nombres de recursos (minusculas, digitos y guiones)."
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

variable "tags" {
  description = "Tags adicionales de los recursos de la plataforma."
  type        = map(string)
  default     = {}
}

# ---------------------------------------------------------------------------
# Imagen del API
# ---------------------------------------------------------------------------
variable "container_registry_id" {
  description = "Id de ARM del Azure Container Registry con la imagen del API."
  type        = string
}

variable "container_registry_login_server" {
  description = "Servidor del registro (p. ej. miregistro.azurecr.io)."
  type        = string
}

variable "api_image" {
  description = "Imagen completa del API (registro/repositorio:tag). La define scripts/deploy.sh."
  type        = string
}

# ---------------------------------------------------------------------------
# Que observa la plataforma
# ---------------------------------------------------------------------------
variable "observed_subscription_ids" {
  description = "Suscripciones sobre las que la identidad de la plataforma recibe Reader."
  type        = list(string)
}

variable "tfstate_sources" {
  description = "Cuentas con estados de Terraform a escanear (lectura de blobs)."
  type = list(object({
    storage_account_id = string
    container          = string
  }))
  default = []
}

# ---------------------------------------------------------------------------
# Organizacion
# ---------------------------------------------------------------------------
variable "app_display_name" {
  description = "Nombre visible de la plataforma."
  type        = string
  default     = "CloudOps Copilot"
}

variable "org_name" {
  description = "Nombre con el que se presentan los agentes."
  type        = string
  default     = "tu organización"
}

variable "mandatory_tags" {
  description = "Tags obligatorias que la plataforma evalua."
  type        = list(string)
  default     = ["Environment", "Project", "ManagedBy"]
}

variable "showback_tags" {
  description = "Dimensiones de atribucion de gasto."
  type        = list(string)
  default     = ["Project", "Environment"]
}

# ---------------------------------------------------------------------------
# Acceso
# ---------------------------------------------------------------------------
variable "allowed_user_object_ids" {
  description = "Object ids de los usuarios que pueden entrar al panel. Vacio = quien ejecuta Terraform."
  type        = list(string)
  default     = []
}

variable "allow_azure_cli" {
  description = "Preautoriza Azure CLI para pedir tokens del API (pruebas y scripts)."
  type        = bool
  default     = true
}

variable "local_redirect_uris" {
  description = "Redirect URIs adicionales para desarrollo local."
  type        = list(string)
  default     = ["http://localhost:5173/"]
}

# ---------------------------------------------------------------------------
# Motor cognitivo (opcional)
# ---------------------------------------------------------------------------
variable "gemini_api_key" {
  description = "API key de Google Gemini. Vacia = motor de reglas local."
  type        = string
  default     = ""
  sensitive   = true
}

variable "gemini_model" {
  description = "Modelo de Gemini."
  type        = string
  default     = "gemini-3.5-flash"
}

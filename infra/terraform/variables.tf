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
# Imagen del API (pública en GitHub Container Registry)
# ---------------------------------------------------------------------------
variable "api_image" {
  description = "Imagen del API al crear la Container App. Después la actualiza el despliegue continuo."
  type        = string
  default     = "ghcr.io/miguelortiz13/cloudops-copilot-api:latest"
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

# ---------------------------------------------------------------------------
# Despliegue continuo
# ---------------------------------------------------------------------------
variable "github_repository" {
  description = <<-EOT
    Repositorio de GitHub autorizado a desplegar, tal como aparece en el claim
    `sub` del token OIDC. Los repositorios nuevos usan el formato inmutable
    `propietario@id/nombre@id`: consultarlo con
    `gh api repos/<propietario>/<nombre> --jq '"\(.owner.login)@\(.owner.id)/\(.name)@\(.id)"'`.
  EOT
  type        = string
  default     = "miguelortiz13@89714460/cloudops-copilot@1406664105"
}

# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------
variable "sql_location" {
  description = "Región de Azure SQL. Puede diferir de `location`: en suscripciones de pago por uso Azure restringe la creación de servidores SQL en algunas regiones (eastus2 y eastus en este caso; error ProvisioningDisabled)."
  type        = string
  default     = "centralus"
}


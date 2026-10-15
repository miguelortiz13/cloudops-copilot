variable "name" {
  description = "Prefijo de los nombres (rol, vista, bucket). Ej.: cloudops-dev."
  type        = string
}

variable "oidc_issuer" {
  description = "Emisor de los tokens sin https://, con la barra final. Entra ID v1: sts.windows.net/<tenant>/."
  type        = string
}

variable "audience" {
  description = "Audiencia (`aud`) que deben traer los tokens: la URI del registro de federación en Entra ID."
  type        = string
}

variable "principal_object_id" {
  description = "Object id de la identidad administrada (claim `sub`). Solo ella puede asumir el rol."
  type        = string
}

variable "cost_export" {
  description = "Crear el export de costos FOCUS a S3. Solo en la cuenta de administración (o una cuenta independiente): cubre a toda la organización."
  type        = bool
  default     = true
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "athena_bytes_limit" {
  description = "Tope de bytes leídos por consulta de Athena (la consulta se cancela al pasarlo). 1 GB = USD 0,005."
  type        = number
  default     = 1073741824
}

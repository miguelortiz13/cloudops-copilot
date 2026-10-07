import os
import re
import json
from typing import Dict, Any, Optional
import google.generativeai as genai

from app.core import config

# Suscripcion de relleno cuando el id recibido no se puede interpretar. Nunca
# debe parecer real: el HCL generado con ella falla en `plan`, no en produccion.
SUSCRIPCION_DESCONOCIDA = "00000000-0000-0000-0000-000000000000"


def _bloque_tags(environment: str) -> str:
    """Bloque `tags = {...}` con el esquema obligatorio de la organizacion."""
    valores = {}
    for tag in config.MANDATORY_TAGS:
        valores[tag] = environment.capitalize() if tag.lower() == "environment" else "por-definir"
    valores["Provisioner"] = "Terraform"
    ancho = max(len(k) for k in valores)
    filas = "\n".join(f'  {k.ljust(ancho)} = "{v}"' for k, v in valores.items())
    return "tags = {\n" + filas + "\n}"

class IaCManager:
    def __init__(self, azure):
        self.azure = azure
        self.gemini_enabled = bool(os.getenv("GEMINI_API_KEY"))
        if self.gemini_enabled:
            genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

    def generate_iac_files(self, resource_id: str, environment: str, domain: str) -> Dict[str, Any]:
        """
        Queries Azure Resource Graph for the resource metadata and uses Gemini (with a robust
        rule-based fallback) to generate Terraform code stacks (main.tf, providers.tf, variables.tf,
        outputs.tf, terraform.tfvars, backend.hcl).
        """
        # Parse resource details from resource ID
        parsed = self._parse_resource_id(resource_id)
        resource_name = parsed["name"]
        resource_type = parsed["type"]
        subscription_id = parsed["subscription_id"]
        resource_group = parsed["resource_group"]

        # 1. Query Azure Resource Graph for the live properties of the resource
        kql = f"resources | where id =~ '{resource_id}' | project name, type, resourceGroup, subscriptionId, location, tags, sku, properties, kind"
        raw_results = self.azure.query_azure_resource_graph(kql)
        
        resource_data = {}
        if raw_results:
            resource_data = raw_results[0]
        else:
            # Fallback data structure if resource is not found in ARG
            resource_data = {
                "name": resource_name,
                "type": resource_type,
                "resourceGroup": resource_group,
                "subscriptionId": subscription_id,
                "location": config.DEFAULT_LOCATION,
                "tags": {"Environment": environment},
                "sku": {"name": "Standard"},
                "properties": {}
            }

        # 2. Try to generate using Gemini if enabled
        if self.gemini_enabled:
            try:
                generated = self._generate_with_gemini(resource_data, environment, domain)
                if generated:
                    return generated
            except Exception as e:
                print(f"Error generating HCL with Gemini: {e}. Falling back to rule-based template.")

        # 3. Fallback to rule-based templates
        return self._generate_with_templates(resource_data, environment, domain, resource_id)

    def _parse_resource_id(self, resource_id: str) -> Dict[str, str]:
        """Helper to extract details from an Azure Resource ID string."""
        # Pattern: /subscriptions/{sub}/resourceGroups/{rg}/providers/{provider}/{type}/{name}
        pattern = r"/subscriptions/([^/]+)/resourceGroups/([^/]+)/providers/([^/]+)/([^/]+)/([^/]+)"
        match = re.search(pattern, resource_id, re.IGNORECASE)
        if match:
            return {
                "subscription_id": match.group(1),
                "resource_group": match.group(2),
                "provider": match.group(3),
                "type": f"{match.group(3)}/{match.group(4)}".lower(),
                "name": match.group(5)
            }
        
        # Simple split fallbacks
        parts = resource_id.strip("/").split("/")
        return {
            "subscription_id": parts[1] if len(parts) > 1 else SUSCRIPCION_DESCONOCIDA,
            "resource_group": parts[3] if len(parts) > 3 else "rg-sin-definir",
            "provider": parts[5] if len(parts) > 5 else "microsoft.compute",
            "type": f"{parts[5]}/{parts[6]}".lower() if len(parts) > 6 else "microsoft.compute/virtualmachines",
            "name": parts[-1] if parts else "resource-name"
        }

    def _generate_with_gemini(self, resource_data: Dict[str, Any], environment: str, domain: str) -> Optional[Dict[str, Any]]:
        """Invokes Gemini to construct standard-compliant HCL stacks."""
        system_instruction = (
            f"Eres el Agente DevOps & SRE Especialista en Terraform de {config.ORG_NAME}.\n"
            "Tu tarea es generar la configuración de Terraform (HCL) completa, limpia y modularizada "
            "siguiendo las mejores prácticas de la compañía.\n\n"
            "REGLAS E IMPOSICIONES DE CÓDIGO:\n"
            "1. Utiliza el proveedor 'azurerm' (versión ~> 3.0 o ~> 4.0).\n"
            "2. Todos los bloques de recursos deben usar variables para la parametrización de entornos, "
            "como el grupo de recursos, la ubicación y el ambiente (por ejemplo: var.environment, var.location).\n"
            "3. Estructura el código en 6 archivos clave: main.tf, providers.tf, variables.tf, outputs.tf, "
            "terraform.tfvars, y backend.hcl.\n"
            "4. En 'providers.tf' incluye el bloque 'import {}' declarativo de Terraform 1.5+ "
            "con el ID del recurso real de Azure para vincularlo sin destruir infraestructura.\n"
            "5. En 'backend.hcl' define la llave del state remoto con el formato:\n"
            f"   {config.IAC_STATE_KEY_PREFIX}/<nombre-suscripcion>/<environment>/<domain>/terraform.tfstate\n"
            f"7. Las tags obligatorias de la organizacion son: {', '.join(config.MANDATORY_TAGS)}.\n"
            "6. Retorna ÚNICAMENTE un objeto JSON válido con las llaves: "
            "main_tf, providers_tf, variables_tf, outputs_tf, terraform_tfvars, backend_hcl. "
            "No incluyas explicaciones en lenguaje natural, Markdown, ni bloques de código de triple acento grave fuera de la respuesta JSON."
        )

        prompt = (
            f"DATOS DEL RECURSO REAL (Azure):\n"
            f"{json.dumps(resource_data, indent=2)}\n\n"
            f"ENTORNO DESTINO: {environment}\n"
            f"DOMINIO TÉCNICO: {domain}\n"
            f"ID DE AZURE: {resource_data.get('name', 'recurso')}\n\n"
            f"Genera los archivos Terraform correspondientes en formato JSON estructurado."
        )

        model = genai.GenerativeModel(
            model_name=config.GEMINI_MODEL,
            system_instruction=system_instruction
        )
        response = model.generate_content(
            contents=[prompt],
            generation_config=genai.types.GenerationConfig(
                temperature=0.1,
                response_mime_type="application/json"
            )
        )

        text = response.text.strip()
        # Strip potential markdown wrapper
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        data = self._primer_objeto_json(text)
        if data is None:
            raise ValueError(
                f"La respuesta del modelo no contenia un objeto JSON legible: {text[:160]}"
            )
        return {
            "main_tf": data.get("main_tf", ""),
            "providers_tf": data.get("providers_tf", ""),
            "variables_tf": data.get("variables_tf", ""),
            "outputs_tf": data.get("outputs_tf", ""),
            "terraform_tfvars": data.get("terraform_tfvars", ""),
            "backend_hcl": data.get("backend_hcl", ""),
            "generation_mode": "gemini_ai"
        }

    @staticmethod
    def _primer_objeto_json(texto: str) -> Optional[Dict[str, Any]]:
        """
        Decodifica el primer objeto JSON completo del texto.

        `json.loads` exige que el texto sea JSON y nada mas, y el modelo suele
        anadir algo despues del objeto —una linea suelta, un segundo bloque—
        aun pidiendole `response_mime_type: application/json`. Eso reventaba con
        "Extra data: line 9 column 1" en cada llamada, de modo que la generacion
        con IA fallaba siempre y caia a las plantillas sin que se notara: la
        interfaz mostraba HCL, solo que nunca el generado por el modelo.

        `raw_decode` lee el primer objeto y devuelve donde termino, que es justo
        lo que hace falta para ignorar lo que venga detras.
        """
        inicio = texto.find("{")
        if inicio == -1:
            return None
        try:
            objeto, _ = json.JSONDecoder().raw_decode(texto[inicio:])
        except json.JSONDecodeError:
            return None
        return objeto if isinstance(objeto, dict) else None

    def _generate_with_templates(self, resource_data: Dict[str, Any], environment: str, domain: str, resource_id: str) -> Dict[str, Any]:
        """Provides high-quality fallback HCL configuration files in case the LLM is rate-limited."""
        name = resource_data.get("name", "resource-name")
        res_type = resource_data.get("type", "microsoft.compute/virtualmachines").lower()
        rg = resource_data.get("resourceGroup", "rg-sin-definir")
        loc = resource_data.get("location", config.DEFAULT_LOCATION)
        sub_id = resource_data.get("subscriptionId", SUSCRIPCION_DESCONOCIDA)

        # Segmento de la suscripcion en la llave del estado: su nombre si Azure
        # lo devolvio, o el id en su defecto.
        sub_slug = re.sub(r"[^a-z0-9]+", "-", str(resource_data.get("subscriptionName") or sub_id).lower()).strip("-")
        backend_key = f"{config.IAC_STATE_KEY_PREFIX}/{sub_slug}/{environment}/{domain}/terraform.tfstate"

        # Generate main.tf based on resource type
        main_tf = ""
        variables_tf = ""
        outputs_tf = ""
        tfvars = ""

        # Virtual Machines Template
        if "virtualmachines" in res_type:
            main_tf = f"""# Archivo main.tf - Auto-generado (Template Fallback)
resource "azurerm_linux_virtual_machine" "{name}" {{
  name                = var.resource_name
  resource_group_name = var.resource_group_name
  location            = var.location
  size                = var.vm_size
  admin_username      = "adminuser"

  network_interface_ids = [
    "/subscriptions/{sub_id}/resourceGroups/{rg}/providers/Microsoft.Network/networkInterfaces/{name}-nic"
  ]

  os_disk {{
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
  }}

  source_image_reference {{
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }}

  tags = var.tags
}}
"""
            variables_tf = """variable "resource_name" {
  type        = string
  description = "Nombre de la maquina virtual"
}

variable "resource_group_name" {
  type        = string
  description = "Nombre del grupo de recursos"
}

variable "location" {
  type        = string
  description = "Region de Azure"
  default     = "__DEFAULT_LOCATION__"
}

variable "vm_size" {
  type        = string
  description = "Size de computo de la maquina"
  default     = "Standard_B2s"
}

variable "tags" {
  type        = map(string)
  description = "Etiquetas obligatorias de gobernanza"
}
"""
            outputs_tf = f"""output "vm_id" {{
  value       = azurerm_linux_virtual_machine.{name}.id
  description = "ID del recurso importado"
}}

output "vm_private_ip" {{
  value       = azurerm_linux_virtual_machine.{name}.private_ip_address
  description = "IP privada asociada"
}}
"""
            tfvars = f"""resource_name       = "{name}"
resource_group_name = "{rg}"
location            = "{loc}"
vm_size             = "Standard_B2s"
{_bloque_tags(environment)}
"""

        # Storage Accounts Template
        elif "storageaccounts" in res_type:
            clean_name = re.sub(r'[^a-z0-9]', '', name.lower())[:24]
            main_tf = f"""# Archivo main.tf - Auto-generado (Template Fallback)
resource "azurerm_storage_account" "{name}" {{
  name                     = var.storage_account_name
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = var.account_tier
  account_replication_type = var.replication_type
  allow_nested_items_to_be_public = false

  tags = var.tags
}}
"""
            variables_tf = """variable "storage_account_name" {
  type        = string
  description = "Nombre de la Storage Account"
}

variable "resource_group_name" {
  type        = string
  description = "Nombre del grupo de recursos"
}

variable "location" {
  type        = string
  default     = "__DEFAULT_LOCATION__"
}

variable "account_tier" {
  type        = string
  default     = "Standard"
}

variable "replication_type" {
  type        = string
  default     = "LRS"
}

variable "tags" {
  type        = map(string)
}
"""
            outputs_tf = f"""output "storage_account_id" {{
  value       = azurerm_storage_account.{name}.id
}}

output "primary_blob_endpoint" {{
  value       = azurerm_storage_account.{name}.primary_blob_endpoint
}}
"""
            tfvars = f"""storage_account_name = "{clean_name}"
resource_group_name  = "{rg}"
location             = "{loc}"
account_tier         = "Standard"
replication_type     = "LRS"
{_bloque_tags(environment)}
"""

        # General/Default Template (if type matches nothing else)
        else:
            type_suffix = res_type.split('/')[-1] if '/' in res_type else "resource"
            main_tf = f"""# Archivo main.tf - Auto-generado (Template Fallback)
# Tipo de recurso: {res_type}
resource "azurerm_resource_group_template_deployment" "{name}" {{
  name                = "{name}-import"
  resource_group_name = var.resource_group_name
  deployment_mode     = "Incremental"
  
  # Este bloque es un fallback generico. Se recomienda reemplazar con
  # el recurso azurerm especifico correspondiente.
  template_content = <<TEMPLATE
{{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
  "contentVersion": "1.0.0.0",
  "resources": []
}}
TEMPLATE
}}
"""
            variables_tf = """variable "resource_group_name" {
  type        = string
}
"""
            outputs_tf = f"""output "import_status" {{
  value = "Template fallback generado para {type_suffix}"
}}
"""
            tfvars = f"""resource_group_name = "{rg}"
"""

        # Write providers.tf including the declarative import block
        # Map Azure type to Terraform resource provider name
        tf_res_type = "azurerm_resource_group_template_deployment"
        if "virtualmachines" in res_type:
            tf_res_type = "azurerm_linux_virtual_machine"
        elif "storageaccounts" in res_type:
            tf_res_type = "azurerm_storage_account"
        elif "networksecuritygroups" in res_type:
            tf_res_type = "azurerm_network_security_group"
        elif "vaults" in res_type:
            tf_res_type = "azurerm_key_vault"
        elif "sites" in res_type:
            tf_res_type = "azurerm_windows_web_app" # or linux
        elif "serverfarms" in res_type:
            tf_res_type = "azurerm_service_plan"

        providers_tf = f"""# Archivo providers.tf - Reconciliacion e Importacion
terraform {{
  required_version = ">= 1.5.0"
  required_providers {{
    azurerm = {{
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }}
  }}
  backend "azurerm" {{}}
}}

provider "azurerm" {{
  features {{}}
}}

# Bloque de importacion declarativo de Terraform 1.5+
import {{
  to = {tf_res_type}.{name}
  id = "{resource_id}"
}}
"""

        backend_hcl = f"""# Archivo backend.hcl - Parametros del estado remoto de Terraform
storage_account_name = "{config.TFSTATE_ACCOUNT or '<cuenta-del-estado>'}"
container_name       = "{config.TFSTATE_CONTAINER}"
key                  = "{backend_key}"
use_oidc             = true
"""

        return {
            "main_tf": main_tf.strip(),
            "providers_tf": providers_tf.strip(),
            "variables_tf": variables_tf.replace("__DEFAULT_LOCATION__", config.DEFAULT_LOCATION).strip(),
            "outputs_tf": outputs_tf.strip(),
            "terraform_tfvars": tfvars.strip(),
            "backend_hcl": backend_hcl.strip(),
            "generation_mode": "local_rules_template"
        }

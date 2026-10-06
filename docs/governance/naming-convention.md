# Convención de nombres de referencia

Plantilla de convención de nombres para recursos de Azure, alineada con las abreviaturas del [Cloud Adoption Framework](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations). La infraestructura de la propia plataforma (`infra/terraform`) la sigue.

## Patrón

```
<tipo>-<carga>-<ambiente>[-<región>][-<instancia>]
```

| Segmento | Descripción | Ejemplo |
|---|---|---|
| `tipo` | Abreviatura CAF del tipo de recurso | `app`, `rg`, `kv` |
| `carga` | Aplicación o servicio | `cloudops`, `billing` |
| `ambiente` | `prod`, `qa`, `dev`, `sbx` | `dev` |
| `región` | Solo si la carga es multi-región | `eus2`, `weu` |
| `instancia` | Solo si hay varias del mismo tipo | `001` |

Todo en minúsculas, separado por guiones, sin caracteres especiales.

## Abreviaturas frecuentes

| Recurso | Abreviatura | Ejemplo |
|---|---|---|
| Resource group | `rg` | `rg-cloudops-dev` |
| App Service plan | `asp` | `asp-cloudops-dev` |
| Web App | `app` | `app-cloudops-dev` |
| Function App | `func` | `func-billing-prod-eus2` |
| Static Web App | `stapp` | `stapp-cloudops-dev` |
| AKS | `aks` | `aks-platform-prod` |
| Container Registry | `cr` | `crplatformprod` |
| Key Vault | `kv` | `kv-billing-prod` |
| Storage account | `st` | `stcloudopsdevdata` |
| Virtual network | `vnet` | `vnet-hub-prod-eus2` |
| Subnet | `snet` | `snet-app-prod` |
| NSG | `nsg` | `nsg-snet-app-prod` |
| Public IP | `pip` | `pip-agw-prod` |
| Application Gateway | `agw` | `agw-edge-prod` |
| SQL Server / DB | `sql` / `sqldb` | `sql-billing-prod` / `sqldb-orders` |
| Log Analytics | `log` | `log-platform-prod` |
| Application Insights | `appi` | `appi-billing-prod` |
| Azure Bot | `bot` | `bot-cloudops-dev` |
| Managed identity | `id` | `id-cloudops-dev` |

## Excepciones de formato

Algunos tipos no admiten guiones o tienen longitud limitada:

| Recurso | Restricción | Cómo se aplica |
|---|---|---|
| Storage account | 3-24, solo minúsculas y dígitos, único global | Sin guiones: `st<carga><ambiente><propósito>` |
| Container Registry | 5-50, alfanumérico, único global | Sin guiones: `cr<carga><ambiente>` |
| Key Vault | 3-24, único global | Acortar la carga si hace falta |
| VM Windows | 15 caracteres de nombre de equipo | Abreviar carga y región |

## Implementación en Terraform

```hcl
locals {
  base         = "${var.workload}-${var.environment}"
  storage_name = substr(replace("st${var.workload}${var.environment}data", "/[^a-z0-9]/", ""), 0, 24)
}

resource "azurerm_resource_group" "rg" {
  name     = "rg-${local.base}"
  location = var.location
  tags     = local.tags
}
```

## Relación con la plataforma

CloudOps Copilot no valida nombres (los nombres no se pueden corregir sin recrear el recurso), pero los nombres autogenerados por el portal —`vnet724`, `basicNsg...`, `<rg>-ip`— son una de las señales más claras de recursos creados a mano, y aparecen con frecuencia entre los candidatos a Shadow IT.

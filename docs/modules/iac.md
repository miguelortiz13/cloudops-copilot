# IaC y Terraform

Código: [`services/tfstate_service.py`](../../backend/app/services/tfstate_service.py), [`agents/iac_generator.py`](../../backend/app/agents/iac_generator.py), [`routers/iac.py`](../../backend/app/routers/iac.py).

## Cobertura real de Terraform

`POST /api/iac/terraform-coverage` lee los estados de Terraform de la cuenta `TFSTATE_ACCOUNT` y cruza sus resource ids con el inventario. **Todo id que aparece en un estado está gestionado, con certeza**; sin ventana de retención y sin heurística.

En un tenant real la diferencia fue reveladora: el conteo por tags reportaba un 8 % de cobertura IaC, y los estados demostraron un **1,1 %**. Las tags miden cuántos equipos etiquetan, no cuánta infraestructura está codificada.

### El estado exonera, pero no acusa

Que un recurso aparezca en un estado prueba que está gestionado y lo saca de los candidatos a Shadow IT. Que **no** aparezca no prueba nada: su equipo puede guardar el estado en otra cuenta. Por eso la regla de tags sigue siendo la que señala, y la respuesta declara sobre cuántos estados se calculó la cifra. Ver [ADR 0004](../adr/0004-el-estado-exonera-pero-no-acusa.md).

### Ids obsoletos

El cruce revela además recursos que un estado sigue gestionando y que **ya no existen en Azure**: alguien los borró sin pasar por Terraform, y el próximo `plan` intentará recrearlos.

Solo cuentan los **recursos de primer nivel** (`/subscriptions/…/resourceGroups/…/providers/<ns>/<tipo>/<nombre>`). Un estado también gestiona subrecursos (contenedores y tablas de storage), recursos de extensión (role assignments), budgets y el propio grupo, que no están en la tabla `resources` de Resource Graph. Antes se contaban como obsoletos: en un proyecto real, 37 de 57 ids aparecían como borrados y ninguno lo estaba (`governance.es_recurso_inventariable`).

### Seguridad

De cada estado solo se extraen `id` y `type`; el resto (llaves, cadenas de conexión) se descarta sin registrarse ni cachearse. Basta `Storage Blob Data Reader` sobre la cuenta.

### Activarlo

```env
# Varias cuentas separadas por comas; opcionalmente cuenta/contenedor
TFSTATE_ACCOUNT=sttfproyectoa,sttfproyectob/estados
TFSTATE_CONTAINER=tfstate
TFSTATE_EXCLUDE_PREFIXES=sandbox/,pruebas/
```

## Generador de HCL

`POST /api/iac/generate` recibe el id de un recurso (por ejemplo, un candidato a Shadow IT), el ambiente y el dominio, y devuelve seis archivos:

| Archivo | Contenido |
|---|---|
| `main.tf` | Recurso `azurerm_*` parametrizado |
| `providers.tf` | Proveedor y bloque `import {}` (Terraform 1.5+) con el id real, para adoptar el recurso sin destruirlo |
| `variables.tf` | Variables con región por defecto `DEFAULT_LOCATION` |
| `outputs.tf` | Salidas útiles |
| `terraform.tfvars` | Valores actuales y bloque `tags` con `MANDATORY_TAGS` |
| `backend.hcl` | Llave `IAC_STATE_KEY_PREFIX/<suscripción>/<ambiente>/<dominio>/terraform.tfstate` |

Con `GEMINI_API_KEY` el código lo genera el modelo a partir de las propiedades reales del recurso; sin ella (o si falla) se usan plantillas locales para VMs, Storage Accounts y un respaldo genérico. El campo `generation_mode` indica cuál se usó.

> El HCL generado es un punto de partida para revisar, no para aplicar a ciegas: ejecuta `terraform plan` y confirma que no propone cambios antes de integrarlo.

## Infraestructura de la propia plataforma

La infraestructura de CloudOps Copilot está en [`infra/terraform`](../../infra/terraform); ver [deployment.md](../deployment.md).

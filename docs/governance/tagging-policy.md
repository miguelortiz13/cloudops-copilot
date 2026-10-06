# Política de tags de referencia

Esta es la política que CloudOps Copilot evalúa por defecto. Es corta a propósito: tres tags que cualquier proyecto puede mantener desde el primer día, y que responden las preguntas que importan al operar. Si tu organización necesita más dimensiones, agrégalas en `MANDATORY_TAGS` y `SHOWBACK_TAGS` (ver [configuration.md](../configuration.md)).

## Tags obligatorias

| Tag | Pregunta que responde | Valores |
|---|---|---|
| `Environment` | ¿En qué ambiente vive? ¿Puedo apagarlo? | `prod`, `qa`, `dev`, `sandbox`, `shared` |
| `Project` | ¿A qué proyecto pertenece y a quién se le atribuye el costo? | Nombre corto del proyecto: `sechub`, `cloudops`, `devops-sre-lab` |
| `ManagedBy` | ¿Cómo se creó y dónde se cambia? | `Terraform`, `Bicep`, `Script`, `Manual` |

Un recurso es **conforme** cuando tiene las tres con un valor útil. No cuentan como valor: vacío, `n/a`, `na`, `tbd`, `none`, `null`, `por confirmar`, `sin definir`.

### `ManagedBy` y la evidencia de IaC

`ManagedBy` con un valor de herramienta (`Terraform`, `Bicep`, `Pulumi`...) cuenta como **evidencia débil** de IaC. Los valores `Manual`, `Portal`, `ClickOps` y `None` declaran lo contrario y **no** cuentan como IaC, aunque la clave exista.

La evidencia fuerte es que el recurso aparezca en un estado de Terraform: configura las cuentas de estados en `TFSTATE_ACCOUNT` y la plataforma lo comprobará (ver [IaC](../modules/iac.md)). Una tag puede mentir; un estado, no.

## Tags recomendadas

| Tag | Uso en la plataforma |
|---|---|
| `Owner` | Identifica al **custodio**. Un recurso sin custodio es una de las cuatro señales de Shadow IT |
| `CostCenter` | Dimensión adicional de showback (agrégala a `SHOWBACK_TAGS`) |
| `component` | Útil para distinguir piezas de un mismo proyecto (`bootstrap`, `api`, `data`) |

Claves de custodio reconocidas: `owner`, `responsable`, `team`, `squad`, `contact`, `custodio`, `ownertech`, `ownerfunc`, `author`, `createdby`. No distinguen mayúsculas y se configuran en `services/governance.py`.

## Reglas de valor

1. **Un vocabulario cerrado por tag.** Los valores libres degradan el showback: `sechub`, `SecHub` y `sec-hub` son tres proyectos para la factura.
2. **`Environment` en minúsculas** y con los valores de la tabla. La plataforma los normaliza para separar producción de no producción.
3. **`Project` igual al prefijo de nombres del proyecto**, para que tags y nombres cuenten la misma historia.
4. Los recursos derivados (nodos de AKS, grupos `MC_*`, `NetworkWatcherRG`, recursos de Databricks) no necesitan tags manuales: la plataforma los excluye de Shadow IT.

## Aplicación

| Mecanismo | Rol |
|---|---|
| **Terraform** | Fuente principal: un `locals { tags = {...} }` común en cada stack. La infraestructura de CloudOps Copilot lo hace así, y el generador de IaC incluye el bloque |
| **Azure Policy** | *Audit* primero; *Deny* para `Environment` y `Project` cuando todos los proyectos cumplan; *Modify* para heredar tags del grupo de recursos |
| **CloudOps Copilot** | Medición continua: matriz de cumplimiento, evolución histórica y lista de no conformes |

## Ejemplo en Terraform

```hcl
locals {
  tags = {
    Environment = var.environment
    Project     = "cloudops"
    ManagedBy   = "Terraform"
  }
}
```

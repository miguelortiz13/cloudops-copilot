# Política de tags de referencia

Esta es la política que CloudOps Copilot evalúa por defecto. Es una plantilla: adáptala a tu organización y refleja el resultado en `MANDATORY_TAGS` y `SHOWBACK_TAGS` (ver [configuration.md](../configuration.md)).

## Objetivo

Que todo recurso de Azure responda, solo con sus tags, a cuatro preguntas: **¿de quién es?**, **¿para qué sirve?**, **¿a quién se le cobra?** y **¿en qué ambiente vive?**

## Tags obligatorias

| Tag | Pregunta que responde | Ejemplos de valor |
|---|---|---|
| `Customer` | ¿A qué cliente (interno o externo) se atribuye el costo? | `Acme`, `Interno` |
| `Tenant` | ¿Qué unidad de negocio o tenant lógico lo consume? | `AcmeRetail`, `Shared` |
| `Platform` | ¿Sobre qué plataforma técnica corre? | `CorePlatform`, `DataPlatform` |
| `Product` | ¿Qué producto o servicio soporta? | `Checkout`, `Billing`, `DevOps` |
| `Suite` | ¿A qué línea o conjunto funcional pertenece? | `Commerce`, `Analytics`, `Shared` |
| `Environment` | ¿En qué ambiente vive? | `Prod`, `QA`, `Dev`, `Sandbox` |

Un recurso es **conforme** cuando tiene las seis con un valor útil. No cuentan como valor: vacío, `n/a`, `na`, `tbd`, `none`, `null`, `por confirmar`, `sin definir`.

## Tags recomendadas

| Tag | Uso en la plataforma |
|---|---|
| `Owner` (o `OwnerTech`, `Team`, `CreatedBy`) | Identifica al **custodio**. Un recurso sin custodio es una de las cuatro señales de Shadow IT |
| `provisioning_method` / `ManagedBy` = `terraform` | **Evidencia débil** de IaC. La evidencia fuerte es aparecer en un estado de Terraform |
| `CostCenter` | Útil como dimensión adicional de showback (`SHOWBACK_TAGS`) |

Claves de custodio reconocidas: `owner`, `responsable`, `team`, `squad`, `contact`, `custodio`, `ownertech`, `ownerfunc`, `author`, `createdby` (sin distinguir mayúsculas). Se configuran en `services/governance.py`.

## Reglas de valor

1. **Valores de una lista cerrada** por tag, publicada y versionada (por ejemplo, en este repositorio). Los valores libres degradan el showback.
2. **PascalCase sin espacios** (`DataPlatform`, no `data platform`).
3. `Environment` usa exactamente `Prod`, `QA`, `Dev`, `Sandbox` o `UAT`; la plataforma los normaliza para distinguir producción de no producción.
4. Los recursos derivados (nodos de AKS, grupos `MC_*`, recursos gestionados por Databricks) **no** necesitan tags manuales: la plataforma los excluye de Shadow IT.

## Aplicación

| Mecanismo | Rol |
|---|---|
| **Terraform** | Fuente principal: un bloque `tags` común (`locals`) en cada stack. El generador de IaC de la plataforma ya lo incluye |
| **Azure Policy** | *Audit* primero; *Deny* para `Environment` y `Owner` cuando la adopción supere el umbral acordado; *Modify* para heredar tags del grupo de recursos |
| **CloudOps Copilot** | Medición continua: matriz de cumplimiento, evolución histórica y lista de no conformes con su custodio |

## Excepciones

Se registran con fecha de vencimiento y responsable. Un recurso exceptuado sigue apareciendo como no conforme: la excepción documenta la decisión, no oculta la métrica.

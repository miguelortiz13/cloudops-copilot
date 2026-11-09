# Runbook: gestionar un hallazgo de seguridad crítico o alto

Los hallazgos salen de las reglas del catálogo (CIS Azure, CIS AWS, CIS Kubernetes e ISO 27001) y se ven en *Riesgo → Hallazgos*. Cada uno trae su remediación.

## Triaje

1. Abrir el hallazgo y leer la remediación y el control que incumple.
2. Ver el recurso en su ficha (*Activos → Recursos*): clasificación (confidencialidad), costo, si está en Terraform y quién lo creó.
3. Decidir: corregir, asumir (con responsable y fecha) o aceptar el riesgo con vencimiento.

## Corregir

- Si el recurso está en Terraform, corregir en el código (por ejemplo `allow_nested_items_to_be_public = false` en una cuenta de almacenamiento, `public_network_access_enabled = false` en un Key Vault) y aplicar con plan y revisión.
- Si está fuera de Terraform, corregir en la nube y considerar importarlo (*Activos → IaC y Terraform* genera el bloque `import`).
- El hallazgo se cierra solo en la próxima recolección cuando la regla deja de fallar.

## Asumir o aceptar el riesgo

- **Asumir**: queda con responsable y fecha objetivo; aparece en *Mis pendientes* de esa persona y sube de urgencia si se atrasa.
- **Aceptar**: con justificación y fecha de vencimiento; al vencer vuelve a estar abierto. Aparece en *Mis pendientes* 14 días antes de vencer.
- **Excepción de control** (*Riesgo → Cumplimiento*): exceptúa un control completo con justificación y vencimiento de hasta un año; la IA puede redactar el borrador.

## Accesos públicos (los más comunes)

- Blob o bucket público: desactivar el acceso público a nivel de cuenta (Azure `allowBlobPublicAccess=false`, AWS *Block Public Access*).
- Key Vault o base alcanzables desde internet: endpoint privado o reglas de red; quitar `0.0.0.0/0`.
- Puertos de administración (22, 3389) abiertos a internet en un NSG o security group: restringir al rango de administración o usar Bastion / Session Manager.

# Operación

Cómo se mantiene la plataforma desplegada: qué recursos tiene, qué cuesta y qué hacer en el día a día. El primer despliegue está en [despliegue](deployment.md); todas las variables, en [configuración](configuration.md).

## Recursos desplegados

Todo se crea con Terraform desde `infra/terraform`, en un grupo de recursos por ambiente (`rg-<prefijo>-<ambiente>`). Hoy existe un solo ambiente, `dev`.

| Recurso | Para qué | Costo/mes |
|---|---|---|
| Container Apps Environment (consumo) | Aloja el API y el job | USD 0 (cupo gratuito) |
| Container App del API | FastAPI, 0 a 1 réplicas, escala a cero | USD 0 |
| Container Apps Job | Job diario de recolección (`collector_cron`) | USD 0 |
| Static Web App Free | Panel React con cabeceras de seguridad | USD 0 |
| Azure SQL, oferta gratuita serverless | Base del modelo canónico; se pausa sola | USD 0 |
| Storage + File Share | Vistas precalculadas, caché de costos, Excel y snapshots | Centavos |
| Identidades administradas | API y job: Reader sobre el alcance observado y lectura de los estados de Terraform | USD 0 |
| App registrations y grupos de Entra ID | API, panel, federación con AWS; un grupo por rol | USD 0 |
| Identidad de despliegue (OIDC) | GitHub Actions despliega sin secretos | USD 0 |
| Módulo `aws-onboarding` (en AWS) | Proveedor OIDC de Entra, rol hub de lectura, Resource Explorer, export FOCUS a S3, Athena y Glue | Centavos |
| Imagen | GitHub Container Registry (gratis en repositorios públicos) | USD 0 |

El total medido está por debajo de USD 5 al mes. La propia plataforma vigila su gasto: el presupuesto mensual por nube avisa al 80 % y al 100 % ([avisos](modules/notifications-reports.md)).

## Configuración clave

| Variable de Terraform | Qué define |
|---|---|
| `observed_subscription_ids`, `observed_management_group_ids` | Alcance de Azure que la plataforma lee |
| `aws_account_id`, `aws_region` | Cuenta de gestión de AWS observada |
| `tfstate_sources` | Cuentas de almacenamiento con estados de Terraform |
| `role_members` | Quién es administrador, operador o lector |
| `mandatory_tags`, `showback_tags` | Esquema de tags de gobernanza y reparto de costos |
| `monthly_budgets_usd` | Presupuesto mensual por nube |
| `notify_webhook_url` | Webhook de avisos (sensible) |
| `gemini_api_key`, `gemini_model` | Modelo del chat (sensible) |
| `collector_cron` | Hora del job diario (UTC) |

Los valores reales van en `terraform.tfvars` y `backend.hcl`, que git ignora. Los sensibles, mejor como variables de entorno `TF_VAR_*`.

## Día a día

| Tarea | Cómo |
|---|---|
| Desplegar código | Automático al mergear a `main` ([despliegue continuo](flows.md#despliegue-continuo)) |
| Ver si el job corrió bien | Administración → estado de recolectores; o la tabla `collector_runs` |
| Reejecutar el job | `az containerapp job start` sobre el job del recolector |
| Revertir un despliegue | Reactivar la revisión anterior de la Container App |
| Dar acceso a alguien | Agregarlo a `role_members` y aplicar Terraform (agregarlo solo al grupo en el portal no le da acceso) |
| Restaurar la base | Backups automáticos de Azure SQL (punto en el tiempo); los datos de las nubes se reconstruyen reejecutando el job |
| Sesión de AWS para administrar | Perfil de IAM Identity Center con `aws sso login`. La plataforma no lo usa: entra a AWS por federación |

## Cambios de infraestructura

1. Exporta los valores sensibles: `TF_VAR_notify_webhook_url` y, si se usa, `TF_VAR_gemini_api_key`. Sin el webhook, el apply borra su secreto.
2. `terraform plan` y revisa que solo cambie lo esperado.
3. `terraform apply`.
4. Si cambió la configuración del job, reejecútalo y revisa Administración.

Si un apply se interrumpe y deja el estado bloqueado, `terraform force-unlock <id>` con el id que muestra el error, y vuelve a aplicar.

## Señales a vigilar

| Señal | Dónde | Qué hacer |
|---|---|---|
| Aviso de recolector caído | Canal de avisos | Ver el error del paso en Administración |
| Paso `parcial` | Administración | Normal si falta un permiso o una cuenta no respondió; revisar el detalle |
| Consumo de la base | Métricas `free_amount_consumed` y `free_amount_remaining` | Si se acerca al cupo, ver las salidas en [infraestructura](plan/05-infraestructura.md#presupuesto-de-cómputo-de-la-base-de-datos) |
| Aviso de presupuesto | Canal de avisos | Revisar el historial de costos por cuenta y servicio |

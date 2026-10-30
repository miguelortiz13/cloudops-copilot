# Configuración

Toda la configuración del backend se lee de variables de entorno. En local se cargan desde `backend/.env` (plantilla: [`backend/.env.example`](../backend/.env.example)); en Azure, de los *app settings* que define Terraform. `load_dotenv` nunca sobrescribe una variable ya definida en el entorno.

El punto de entrada es [`app/core/config.py`](../backend/app/core/config.py). Algunos servicios leen además sus propios parámetros de ajuste fino; todos aparecen abajo.

## Organización

| Variable | Defecto | Descripción |
|---|---|---|
| `APP_NAME` | `CloudOps Copilot` | Nombre visible en la API y en el panel |
| `ORG_NAME` | `tu organización` | Nombre con el que se presentan los agentes en el chat |
| `MANDATORY_TAGS` | `Environment,Project,ManagedBy` | Tags obligatorias. Cambian el KPI de cumplimiento, la matriz de tags, la regla de Shadow IT, las consultas del chat y las plantillas de Terraform. Ver [política de tags](governance/tagging-policy.md) |
| `SHOWBACK_TAGS` | `Project,Environment` | Dimensiones de atribución de gasto en FinOps |
| `FRONTEND_URL` | `http://localhost:5173` | URL pública del panel; enlaces en tarjetas de Teams y origen CORS por defecto |
| `ALLOWED_ORIGINS` | `FRONTEND_URL` + `localhost:5173` | Orígenes CORS, separados por comas. Nunca `*` |
| `DATA_DIR` | `backend/data` | Directorio persistente (caché de costos, histórico, Excel, snapshots). `EXCEL_STORAGE_DIR` se acepta como alias heredado |
| `DEFAULT_LOCATION` | `eastus2` | Región por defecto en el HCL generado |

## Credenciales de Azure

| Variable | Descripción |
|---|---|
| `AZURE_TENANT_ID` | Tenant de Entra ID |
| `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` | Service Principal de la plataforma (también firma los mensajes proactivos del bot) |
| `AZURE_READER_CLIENT_ID` / `AZURE_READER_CLIENT_SECRET` | Service Principal lector alternativo. Si está definido, tiene prioridad para consultar el tenant |
| `AZURE_SUBSCRIPTION_ID` | Suscripción por defecto |
| `AZURE_ALLOWED_SUBSCRIPTIONS` | Lista blanca de suscripciones (ids separados por comas). Vacío = todas las visibles |

Sin Service Principal, el agente usa `DefaultAzureCredential`: la **identidad administrada** en Azure (`AZURE_MANAGED_IDENTITY_CLIENT_ID` si es asignada por el usuario) o la sesión de `az login` en local. La conexión se confirma pidiendo un token al arrancar; si falla, `/api/inventory/health` lo refleja.

| Variable | Defecto | Descripción |
|---|---|---|
| `AZURE_MANAGED_IDENTITY_CLIENT_ID` | vacío | Client id de la identidad administrada asignada por el usuario |
| `AZURE_CLI_TIMEOUT_SECONDS` | `30` | Espera máxima a `az` al pedir un token (en WSL tarda ~8 s) |

 **Cuidado en local:** si tu `az login` apunta a un tenant real, la plataforma lo consultará.

## Motor cognitivo

| Variable | Defecto | Descripción |
|---|---|---|
| `GEMINI_API_KEY` | vacío | Sin clave, el chat y el generador de IaC usan el motor de reglas local |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Modelo usado por el chat, el agente SRE y el generador de IaC |

## Autenticación

| Variable | Defecto | Descripción |
|---|---|---|
| `AUTH_ENABLED` | `false` | Exige bearer token de Entra ID en todas las rutas salvo `/`, `/api/inventory/health` y `/api/teams/webhook` |
| `AZURE_AD_TENANT_ID` | — | Tenant emisor de los tokens |
| `AZURE_AD_API_CLIENT_ID` | — | Audiencia: App Registration que representa al API |
| `BOT_AUTH_ENABLED` | `true` | Valida el JWT de Bot Framework en el webhook de Teams |
| `MICROSOFT_APP_ID` | `AZURE_CLIENT_ID` | App Id del bot (audiencia esperada) |
| `TEAMS_WEBHOOK_URL` | vacío | Webhook entrante opcional para el reporte semanal |
| `MONTHLY_BUDGETS_USD` | vacío | Presupuesto mensual por nube para los avisos (`azure=5,aws=5`): al 80 % y al 100 % del gasto del mes, y si el pronóstico lo supera. En Terraform, `monthly_budgets_usd` |
| `NOTIFY_WEBHOOK_URL` | vacío | Webhook de Discord, Slack o Teams (Workflows) para los avisos del job: hallazgos altos o críticos nuevos, recolectores con dos fallas seguidas, costos y el reporte ejecutivo mensual (el día 4; en Discord, con el PDF adjunto). En Terraform, `TF_VAR_notify_webhook_url` |

## Costos (Cost Management)

| Variable | Defecto | Descripción |
|---|---|---|
| `COST_WINDOW_DAYS` | `30` | Ventana de gasto consultada |
| `COST_CACHE_TTL_SECONDS` | `21600` | Vigencia de la caché (Cost Management consolida una vez al día) |
| `COST_CACHE_PERSIST` | `true` | Persistir la caché en `DATA_DIR/cost_cache` |
| `COST_CACHE_MAX_AGE_SECONDS` | `604800` | Edad máxima de una entrada persistida antes de descartarla |
| `COST_DENIAL_TTL_SECONDS` | `3600` | Cuánto se recuerda un `403` antes de volver a probar la suscripción |
| `COST_MAX_CONCURRENT` | `2` | Consultas simultáneas a Cost Management |
| `COST_SUB_WORKERS` | `8` | Hilos por reporte bajo demanda |
| `COST_REQUEST_TIMEOUT` | `45` | Timeout por petición (s) |
| `COST_MAX_THROTTLE_WAIT` | `25` | Espera máxima ante `Retry-After` (s) |
| `COST_WARM_ENABLED` | `true` | Precarga en segundo plano |
| `COST_WARM_INTERVAL_SECONDS` | `21600` | Intervalo entre precargas |
| `COST_WARM_INITIAL_DELAY_SECONDS` | `20` | Espera tras el arranque |
| `COST_WARM_PACE_SECONDS` | `9` | Pausa entre suscripciones |
| `COST_WARM_RETRY` | `true` | Segunda pasada sobre las que fallaron por `429` |
| `COST_WARM_RETRY_BACKOFF` | `60` | Espera antes de la segunda pasada |
| `COST_WARM_RETRY_PACE_FACTOR` | `2` | Multiplicador de pausa en la segunda pasada |

## Métricas (Azure Monitor)

| Variable | Defecto | Descripción |
|---|---|---|
| `METRICS_CACHE_TTL_SECONDS` | `3600` | Caché de CPU promedio por VM |
| `METRICS_MAX_WORKERS` | `8` | Consultas paralelas |
| `METRICS_REQUEST_TIMEOUT` | `20` | Timeout por petición (s) |

## Estados de Terraform

| Variable | Defecto | Descripción |
|---|---|---|
| `TFSTATE_ACCOUNT` | vacío | Cuentas con estados a escanear, separadas por comas, opcionalmente `cuenta/contenedor`. **Vacía = módulo desactivado**. Una cuenta inaccesible no invalida las demás |
| `TFSTATE_CONTAINER` | `tfstate` | Contenedor por defecto de las cuentas sin contenedor explícito |
| `TFSTATE_ENABLED` | `true` | Interruptor general |
| `TFSTATE_EXCLUDE_PREFIXES` | vacío | Prefijos de blob a ignorar |
| `TFSTATE_CACHE_TTL_SECONDS` | `21600` | Vigencia del índice de ids gestionados |
| `TFSTATE_REQUEST_TIMEOUT` | `30` | Timeout por blob (s) |
| `TFSTATE_WORKERS` | `6` | Descargas paralelas |
| `TFSTATE_ID_BATCH` | `150` | Ids por lote al cruzar con Resource Graph |
| `TFSTATE_MAX_IDS_KQL` | `2000` | Máximo de ids embebidos en una consulta KQL |
| `IAC_STATE_KEY_PREFIX` | `platform/azure` | Prefijo de la llave del estado en el HCL generado |

## Inventario y servidor

| Variable | Defecto | Descripción |
|---|---|---|
| `INVENTORY_CACHE_TTL_SECONDS` | `300` | Caché de inventario |
| `PORT` / `HOST` | `8000` / `127.0.0.1` | Solo informativos en local; uvicorn recibe los suyos por línea de comandos |

## Kubernetes

| Variable | Descripción |
|---|---|
| `K8S_CLUSTERS` | Clústeres que reportan con el agente, separados por coma. En Terraform, `kubernetes_clusters` |
| `K8S_SNAPSHOT_ACCOUNT` | Cuenta de almacenamiento donde los agentes dejan sus fotos (la de la plataforma) |
| `NOTIFY_WEBHOOK_URL` (job `k8s-watch`) | Destino de los avisos de Kubernetes; el job corre según `kubernetes_watch_cron` (por defecto cada 10 minutos) |
| `ALERTS_INGEST_TOKEN` | Token con que Alertmanager envía alertas a `/api/alerts/alertmanager`; sin él la ingesta responde 503. En Terraform lo genera `random_password.alerts_ingest` (output `alerts_ingest_token`) |
| `K8S_EXCLUDED_NAMESPACES` | Namespaces cuyas cargas no se evalúan con las reglas `k8s.*` (por defecto `kube-system,kube-public,kube-node-lease`) |
| `INCLUDE_LOGS` (Deployment del agente) | `false` para que la foto no lleve líneas de log de los pods con problemas |

Guía del agente en [Kubernetes](modules/kubernetes-sre.md#conectar-un-clúster).

## Frontend (tiempo de compilación)

Plantilla: [`frontend/.env.example`](../frontend/.env.example).

| Variable | Descripción |
|---|---|
| `VITE_API_URL` | URL del backend (`http://localhost:8000` por defecto) |
| `VITE_USER_DISPLAY_NAME` / `VITE_USER_ROLE` | Nombre y rol mostrados en el panel |
| `VITE_AZURE_AD_CLIENT_ID`, `VITE_AZURE_AD_TENANT_ID`, `VITE_API_SCOPE` | Login con Entra ID; las tres o ninguna |

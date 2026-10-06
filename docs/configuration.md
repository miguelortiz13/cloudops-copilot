# Configuración

Toda la configuración del backend se lee de variables de entorno. En local se cargan desde `backend/.env` (plantilla: [`backend/.env.example`](../backend/.env.example)); en Azure, de los *app settings* que define Terraform. `load_dotenv` nunca sobrescribe una variable ya definida en el entorno.

El punto de entrada es [`app/core/config.py`](../backend/app/core/config.py). Algunos servicios leen además sus propios parámetros de ajuste fino; todos aparecen abajo.

## Organización

| Variable | Defecto | Descripción |
|---|---|---|
| `APP_NAME` | `CloudOps Copilot` | Nombre visible en la API y en el panel |
| `ORG_NAME` | `tu organización` | Nombre con el que se presentan los agentes en el chat |
| `MANDATORY_TAGS` | `Customer,Tenant,Platform,Product,Suite,Environment` | Tags obligatorias. Cambian el KPI de cumplimiento, la matriz de tags, la regla de Shadow IT, las consultas del chat y las plantillas de Terraform. Ver [política de tags](governance/tagging-policy.md) |
| `SHOWBACK_TAGS` | `Customer,Product,Suite,Environment` | Dimensiones de atribución de gasto en FinOps |
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

Sin Service Principal, el agente intenta `DefaultAzureCredential` (por ejemplo, la sesión de `az login`). **Cuidado en local:** si tu `az login` apunta a un tenant real, la plataforma lo consultará.

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
| `TFSTATE_ACCOUNT` | vacío | Cuenta con los estados a escanear. **Vacía = módulo desactivado** |
| `TFSTATE_CONTAINER` | `tfstate` | Contenedor de los estados |
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

## Kubernetes SRE

| Variable | Descripción |
|---|---|
| `K8S_CLUSTER_NAME` | Clúster AKS a diagnosticar |
| `K8S_RESOURCE_GROUP` | Su grupo de recursos |
| `K8S_SUBSCRIPTION_ID` | Su suscripción |

Con alguna vacía el agente queda en modo *offline*.

## Frontend (tiempo de compilación)

Plantilla: [`frontend/.env.example`](../frontend/.env.example).

| Variable | Descripción |
|---|---|
| `VITE_API_URL` | URL del backend (`http://localhost:8000` por defecto) |
| `VITE_USER_DISPLAY_NAME` / `VITE_USER_ROLE` | Nombre y rol mostrados en el panel |
| `VITE_AZURE_AD_CLIENT_ID`, `VITE_AZURE_AD_TENANT_ID`, `VITE_API_SCOPE` | Login con Entra ID; las tres o ninguna |

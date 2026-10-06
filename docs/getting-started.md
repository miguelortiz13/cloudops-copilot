# Primeros pasos

## Requisitos

| Herramienta | Versión | Para |
|---|---|---|
| Python | 3.11+ (probado con 3.12) | Backend |
| Node.js | 20+ (probado con 22) | Frontend |
| Azure CLI | 2.60+ | Autenticación local y despliegue |
| Terraform | 1.5+ | Solo para desplegar |
| Docker | opcional | Entorno completo en contenedores |

## 1. Identidad de solo lectura

La plataforma necesita un Service Principal con rol **`Reader`** sobre las suscripciones (o el management group) que quieres observar:

```bash
az ad sp create-for-rbac \
  --name sp-cloudops-copilot-reader \
  --role Reader \
  --scopes /subscriptions/<SUBSCRIPTION_ID>
```

Guarda `appId`, `password` y `tenant`. Detalle de roles opcionales (costos a nivel de management group, Monitoring Reader, lectura de estados de Terraform) en [deployment.md](deployment.md#permisos).

> Puedes saltarte este paso: sin Service Principal la plataforma usa tu sesión de `az login`. Asegúrate de que apunte al tenant que quieres consultar.

## 2. Instalación

```bash
git clone git@github.com:miguelortiz13/cloudops-copilot.git
cd cloudops-copilot
make setup
```

`make setup` crea `backend/.venv`, instala dependencias de ambos lados y copia `backend/.env.example` a `backend/.env`.

> En Ubuntu/WSL, `python3 -m venv` requiere el paquete `python3-venv` (`sudo apt install python3.12-venv`).

## 3. Configuración mínima

Edita `backend/.env`:

```env
ORG_NAME=Acme Corp
AZURE_TENANT_ID=<tenant>
AZURE_CLIENT_ID=<appId>
AZURE_CLIENT_SECRET=<password>
AZURE_SUBSCRIPTION_ID=<suscripción por defecto>
GEMINI_API_KEY=            # opcional
```

El esquema de tags por defecto es `Environment`, `Project`, `ManagedBy`; si usas otro, defínelo en `MANDATORY_TAGS`. Referencia completa en [configuration.md](configuration.md).

## 4. Ejecutar

```bash
make dev
```

| Servicio | URL |
|---|---|
| Panel | http://localhost:5173 |
| API | http://localhost:8000 |
| Documentación interactiva (Swagger) | http://localhost:8000/docs |

### Con Docker

```bash
docker compose up --build
```

Panel en http://localhost:8080 y API en http://localhost:8000. Los datos persisten en el volumen `cloudops-data`.

## 5. Verificar

```bash
curl -s localhost:8000/api/inventory/health | python3 -m json.tool
```

`"azureConnected": true` indica que la autenticación funciona. Luego abre el panel y selecciona tus suscripciones en el menú superior.

## 6. Pruebas

```bash
make test               # pruebas unitarias, sin red ni .env local
make lint               # ruff + eslint
make test-integration   # compara KQL vs memoria contra tu tenant (requiere credenciales)
```

## Problemas frecuentes

| Síntoma | Causa probable |
|---|---|
| `azureConnected: false` | Credenciales incompletas o secreto expirado. Revisa el log de arranque |
| FinOps muestra todo como *estimado* | Falta permiso de costos, o Cost Management respondió `429`. Mira `cost_data.coverage` y `/api/finops/warm-status` |
| El panel no carga datos (CORS) | `VITE_API_URL` o `ALLOWED_ORIGINS` no coinciden con la URL real |
| El chat responde sin IA | Falta `GEMINI_API_KEY` o el modelo no está disponible; el campo `mode` de la respuesta lo indica |
| Kubernetes en modo *offline* | Falta alguna de las variables `K8S_*` |

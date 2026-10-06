# Roadmap

Lo que falta para llevar CloudOps Copilot de herramienta interna a producto desplegable por terceros. Ordenado por prioridad dentro de cada bloque.

## 1. Producción segura

- [ ] `AUTH_ENABLED=true` por defecto en Terraform y documentar el registro de las dos App Registrations con un script (`az ad app create`).
- [ ] Secretos en **Key Vault** con referencias `@Microsoft.KeyVault(...)` en los app settings, e identidad administrada del App Service en lugar de client secret.
- [ ] Autenticación de Terraform y despliegue por **OIDC** desde GitHub Actions (workflow de CD con `environment` protegido).
- [ ] Autorización por rol (lector / operador) además de autenticación: el agente SRE y el pipeline solo para operadores.
- [ ] Límite de tasa en `/api/chat` y `/api/k8s/chat`.

## 2. Calidad del backend

- [ ] Inyectar servicios con `Depends` de FastAPI en lugar de la tupla de `get_services()`.
- [ ] Retirar los `from x import *` de los routers.
- [ ] Propagar `forceRefresh` en el camino KQL de `/api/inventory/resources` (hoy se ignora; marcado con `TODO`).
- [ ] Retirar endpoints heredados (`/api/stats`, `/api/resources`, `/api/subscriptions`, `/api/recommendations*`) cuando el panel deje de usarlos.
- [ ] Logging estructurado (JSON) en lugar de `print`, con correlación por petición; exportar a Application Insights.
- [ ] Pruebas de routers con `TestClient` y cobertura medida en CI.
- [ ] Hacer configurables las claves de custodio y de evidencia IaC (`governance.py`) igual que las tags obligatorias.

## 3. IA

- [ ] Migrar de `google-generativeai` (en desuso) a `google-genai`.
- [ ] Abstraer el proveedor de LLM (Gemini, Azure OpenAI, Claude) detrás de una interfaz común.
- [ ] Respuestas en streaming en el chat.
- [ ] Evaluaciones automáticas del agente: un conjunto de preguntas con respuestas verificables contra el tenant de prueba.

## 4. Frontend

- [ ] Dividir `App.tsx` por módulo (inventario, FinOps, SecOps, IaC, Kubernetes, chat).
- [ ] Tipar las respuestas del API (generar tipos desde el OpenAPI) y volver `no-explicit-any` a error.
- [ ] Pruebas de componentes (Vitest + Testing Library).
- [ ] Modo claro y accesibilidad (contraste, navegación por teclado).

## 5. Producto

- [ ] Base de datos opcional (PostgreSQL) para histórico de largo plazo y hallazgos con ciclo de vida (abierto, aceptado, resuelto), reemplazando los stubs de recomendaciones.
- [ ] Alertas programadas a Teams/Slack sobre umbrales (nuevo hallazgo crítico, anomalía de costo).
- [ ] Remediación asistida: abrir un PR con el HCL generado en el repositorio de infraestructura.
- [ ] Soporte multi-nube (AWS Config / Resource Explorer, GCP Asset Inventory) detrás de la misma interfaz de servicios.
- [ ] Empaquetado como Helm chart para AKS.

## Hecho en la v2.1

Ver [CHANGELOG](../CHANGELOG.md).

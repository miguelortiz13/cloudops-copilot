# Roadmap

> Este es el registro de tareas pendientes. El análisis completo —arquitectura objetivo, multinube y fases con criterios de salida— está en el **[plan de evolución](plan/README.md)**.

Lo que falta para llevar CloudOps Copilot de herramienta interna a producto desplegable por terceros. Ordenado por prioridad dentro de cada bloque.

## 1. Producción segura

- [x] `AUTH_ENABLED=true` en el despliegue y app registrations gestionadas por Terraform, con acceso solo para usuarios asignados.
- [x] Identidad administrada en lugar de client secrets.
- [ ] Clave de Gemini desde Key Vault (referencia de secreto de Container Apps).
- [ ] Autenticación de Terraform y despliegue por **OIDC** desde GitHub Actions (workflow de CD con `environment` protegido).
- [ ] Autorización por rol (lector / operador) además de autenticación: el agente SRE y el pipeline solo para operadores.
- [ ] Volver a aprovisionar el bot de Teams con la arquitectura de Container Apps (registro con credencial federada, sin secreto).
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

- [x] Rediseño completo por módulos, con sistema de diseño en tokens.
- [x] Contratos del API tipados; `no-explicit-any` como error.
- [x] Modo claro y oscuro.
- [ ] Generar `lib/types.ts` desde el OpenAPI en lugar de mantenerlo a mano.
- [ ] Pruebas de componentes (Vitest + Testing Library) y capturas de regresión visual con Playwright.
- [ ] Revisión de accesibilidad con lector de pantalla y navegación completa por teclado.
- [ ] Filtro de rango de fechas en Costos (7 / 30 / 90 días).

## 5. Producto

- [ ] Base de datos opcional (PostgreSQL) para histórico de largo plazo y hallazgos con ciclo de vida (abierto, aceptado, resuelto), reemplazando los stubs de recomendaciones.
- [ ] Alertas programadas a Teams/Slack sobre umbrales (nuevo hallazgo crítico, anomalía de costo).
- [ ] Remediación asistida: abrir un PR con el HCL generado en el repositorio de infraestructura.
- [ ] Soporte multi-nube (AWS Config / Resource Explorer, GCP Asset Inventory) detrás de la misma interfaz de servicios.
- [ ] Empaquetado como Helm chart para AKS.

## Hecho en la v2.1

Ver [CHANGELOG](../CHANGELOG.md).

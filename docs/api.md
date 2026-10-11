# API

La especificación OpenAPI completa y navegable está en `/docs` (Swagger) y `/redoc` del backend. Este documento resume los endpoints por módulo.

**Autenticación:** con `AUTH_ENABLED=true`, todas las rutas exigen `Authorization: Bearer <token de Entra ID>` salvo las marcadas como públicas. Ver [security.md](security.md).

**Scope:** la mayoría de endpoints aceptan `subscriptionIds` (lista vacía = todas las suscripciones visibles, filtradas por `AZURE_ALLOWED_SUBSCRIPTIONS`).

## Inventario y gobernanza

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/inventory/health` | **Pública.** Estado de la conexión con Azure; nunca expone secretos |
| `GET` | `/api/inventory/subscriptions` | Suscripciones accesibles por la identidad de la plataforma |
| `POST` | `/api/inventory/resources` | Recursos paginados y filtrados, con datos de gobernanza normalizados |
| `POST` | `/api/inventory/summary` | KPIs y distribuciones (registra además el punto histórico del día) |
| `POST` | `/api/inventory/tag-compliance` | Matriz de cumplimiento de las tags obligatorias |
| `POST` | `/api/inventory/history` | Serie histórica de KPIs y deltas del período |
| `POST` | `/api/inventory/manual-creations` | Recursos creados a mano según el historial de cambios (ventana ~14 días) |
| `POST` | `/api/inventory/export` | CSV UTF-8 con BOM generado en memoria |
| `GET` | `/api/inventory/snapshots` | Snapshots del pipeline de inventario |
| `GET` | `/api/inventory/download/{filename}` | Descarga de un snapshot o del Excel maestro |

Ejemplo:

```bash
curl -s -X POST localhost:8000/api/inventory/resources \
  -H 'Content-Type: application/json' \
  -d '{"subscriptionIds": [], "page": 1, "pageSize": 25,
       "filters": {"onlyNonCompliant": true}}'
```

## Cumplimiento

Detalle en [modules/compliance.md](modules/compliance.md). Leen de la base (vista precalculada por el recolector); sin base responden 503.

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/compliance` | Estado de cada control de CIS Azure 2.0.0 e ISO 27001:2022 con su evidencia, y catálogo de reglas |
| `GET` | `/api/compliance/assets` | Activos con clasificación ISO, tríada C-I-D, custodio y hallazgos activos |
| `GET` | `/api/compliance/assets/export` | El inventario clasificado en CSV |
| `POST` | `/api/compliance/assets/classification` | **Operador.** Clasificación manual con motivo (auditada) |
| `POST` | `/api/compliance/assets/classification/restore` | **Operador.** Vuelve a la clasificación automática (auditada) |

## Administración

Solo para el rol administrador. Abren la base (la despiertan si estaba pausada): se consultan cuando alguien los pide, nunca desde una sonda.

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/admin/audit` | Últimas acciones auditadas |
| `GET` | `/api/admin/accounts` | Cuentas conectadas por proveedor: visibles en la última recolección, permiso de costos (con permiso, sin permiso, falló), recursos, hallazgos activos y gasto de 30 días; capacidades del proveedor con el motivo de las que faltan, e identidad con la que se conecta |
| `GET` | `/api/admin/database` | Versión del esquema, filas por tabla y últimas ejecuciones de los recolectores |

## FinOps

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/finops/costs` | Visión global: totales de 30 días vs. los 30 anteriores, mes en curso, proyección, serie diaria de 60 días, desgloses por suscripción, grupo, servicio, región y tags, y ranking de recursos |
| `GET` | `/api/finops/report` | Reporte completo: huérfanos, showback, anomalías, presupuestos, right-sizing, cobertura de costo |
| `GET` | `/api/finops/warm-status` | Estado de la precarga de costos en segundo plano |
| `GET` | `/api/finops/details` | *Heredado.* Conteos básicos de huérfanos |

## SecOps

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/secops/report` | Hallazgos clasificados por severidad |
| `GET` | `/api/secops/exposure` | Hallazgos priorizados por severidad y gasto expuesto |
| `GET` | `/api/secops/details` | *Heredado.* Conteos básicos de NSG y recursos fallidos |

## IaC

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/iac/generate` | Genera `main.tf`, `providers.tf` (con `import {}`), `variables.tf`, `outputs.tf`, `terraform.tfvars` y `backend.hcl` para un recurso |
| `POST` | `/api/iac/terraform-coverage` | Cobertura real de Terraform leída de los estados, con ids obsoletos |

## Agentes de IA

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/chat` | Pregunta a un agente: `{"message", "agent_type": "inventory\|finops\|secops", "subscriptions"}`. La respuesta indica `mode` (IA o reglas) |

## Kubernetes SRE

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/k8s/health` | Conectividad con el clúster configurado |
| `GET` | `/api/k8s/clusters` | Clústeres AKS visibles |
| `POST` | `/api/k8s/overview` | Nodos, pods, servicios y score de salud |
| `POST` | `/api/k8s/incidents` | Incidencias activas por severidad |
| `GET` | `/api/k8s/pod-logs` | Últimas líneas de log de un pod (parámetros validados RFC 1123) |
| `POST` | `/api/k8s/chat` | Chat del agente SRE con contexto del clúster |
| `POST` | `/api/k8s/reinit` | Reinicializa la conexión |

## Pipeline de inventario

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/sync` | Lanza el pipeline semanal en segundo plano |
| `GET` | `/api/sync/status` | Estado y log en vivo del pipeline |

## Integraciones

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/teams/webhook` | **Pública** (autenticada con JWT de Bot Framework). Mensajes del bot de Teams |
| `POST` | `/api/integration/test-webhook` | Envía una alerta de prueba (inventario, FinOps o SecOps) a un webhook entrante |

## Heredados y en desuso

Se conservan por compatibilidad con versiones anteriores del panel. Serán retirados (ver [roadmap](roadmap.md)).

| Método | Ruta | Reemplazo |
|---|---|---|
| `GET` | `/` | `/api/inventory/health` |
| `GET` | `/api/stats` | `/api/inventory/summary` |
| `GET` | `/api/resources` | `/api/inventory/resources` |
| `GET` | `/api/subscriptions` | `/api/inventory/subscriptions` |
| `GET/POST` | `/api/recommendations*` | Stubs desactivados; devuelven listas vacías |

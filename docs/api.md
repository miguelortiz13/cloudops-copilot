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
| `GET` | `/api/k8s/clusters` | Clústeres que reportan con el agente: distribución, versión, nodos, pods, salud y antigüedad de la foto |
| `GET` | `/api/k8s/clusters/{nombre}` | Detalle desde la última foto: incidencias, nodos, cargas, pods con problemas y eventos de advertencia |
| `POST` | `/api/k8s/chat` | **Operador.** Chat del agente SRE sobre la última foto del clúster (`clusterName` opcional) |

## Historia, hallazgos y reportes (desde la base)

Responden desde las vistas que deja el job ([modelo de datos](data-model.md#lecturas-sin-abrir-la-base)). Sin base configurada, o con la base pausada por agotar el cupo gratuito, responden `503` y el panel vuelve a las vistas en vivo. `accounts` es el filtro del panel: uids separados por coma (vacío = todas).

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/accounts` | Cuentas de todas las nubes para el filtro del panel |
| `GET` | `/api/history/costs?period=&accounts=` | Costos por periodo (`7d`, `30d`, `90d`, `mtd`, `last_month`): total, comparación, serie diaria, por servicio, cuenta, recurso y mes |
| `GET` | `/api/history/kpis?days=` | KPIs de gobernanza de 7 a 400 días |
| `GET` | `/api/findings` | Hallazgos de todas las nubes con su estado |
| `GET` | `/api/findings/{id}/events` | Historia de un hallazgo |
| `POST` | `/api/findings/{id}/status` | **Operador.** Asumir, aceptar con vencimiento o reabrir; queda auditado |
| `GET` | `/api/inventory/report` | Inventario multinube por cuenta, tipo y región, con gasto y cobertura de Terraform |
| `GET` | `/api/inventory/report/export?accounts=` | El mismo inventario en CSV |
| `GET` | `/api/reports/monthly?month=AAAA-MM` | Reporte ejecutivo del mes en PDF ([avisos y reportes](modules/notifications-reports.md)) |

## Incidentes

Ver [incidentes](modules/incidents.md#api): `POST /api/alerts/alertmanager` (pública con su propio token), `GET /api/incidents`, `GET /api/incidents/{id}` y `POST /api/incidents/{id}/feedback`.

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

Se conservan por compatibilidad con versiones anteriores del panel. Serán retirados (ver [pendientes](roadmap.md#deuda-técnica)).

| Método | Ruta | Reemplazo |
|---|---|---|
| `GET` | `/` | `/api/inventory/health` |
| `GET` | `/api/stats` | `/api/inventory/summary` |
| `GET` | `/api/resources` | `/api/inventory/resources` |
| `GET` | `/api/subscriptions` | `/api/inventory/subscriptions` |
| `GET/POST` | `/api/recommendations*` | Stubs desactivados; devuelven listas vacías |

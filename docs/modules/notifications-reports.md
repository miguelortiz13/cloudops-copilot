# Avisos y reportes

La plataforma avisa sola en un canal de Discord, Slack o Teams y envía un reporte ejecutivo cada mes. Los dos son los últimos pasos del [job diario](../flows.md#job-diario-de-recolección) y usan el mismo webhook (`NOTIFY_WEBHOOK_URL`).

## Eventos

| Evento | Cuándo | Se repite |
|---|---|---|
| `finding.opened` | Un hallazgo de severidad alta o crítica se detecta, se reabre o vence su aceptación, y sigue abierto | No: solo existe en la transición |
| `collector.failed` | Las dos últimas ejecuciones de un recolector fallaron | Cada día mientras siga caído (es un recordatorio) |
| `resource.unmanaged_created` | Apareció un recurso que ningún estado de Terraform contiene y que creó una persona según Activity Log o CloudTrail; el aviso dice quién | No: solo cuenta lo aparecido desde el último aviso |
| `cost.anomaly` | En los últimos 3 días completos, una cuenta gastó más que la media de los 14 días previos + 3 desviaciones, o más del doble; mínimo 0,50 USD | No: clave `anomalia:{cuenta}:{día}` |
| `budget.threshold` | El gasto del mes de una nube llega al 80 % o al 100 % de `MONTHLY_BUDGETS_USD`, o desde el día 8 el pronóstico lineal lo supera | No: clave `presupuesto:{nube}:{mes}:{nivel}` |

Los avisos de Kubernetes (incidencias de clúster y agente sin reportar) salen del job `k8s-watch` cada 10 minutos, al mismo webhook: ver [Kubernetes](kubernetes-sre.md#avisos).

Para `resource.unmanaged_created`, un recurso sin estados de Terraform conectados (cobertura desconocida) o creado por una automatización (Terraform, un pipeline, un servicio de la nube) no cuenta, ni el inventario de una cuenta recién conectada. Si el creador se conoce recién días después de que el recurso apareció, ese recurso no se avisa.

Un día sin filas de costo cuenta como 0: pasar de nada a gastar también es anomalía. El presupuesto se configura en Terraform (`monthly_budgets_usd`, por ejemplo `{ azure = 5, aws = 5 }`).

## Destino según el webhook

| Host | Formato |
|---|---|
| `discord.com` | Embed con enlace al panel; el reporte mensual va con el PDF adjunto |
| `hooks.slack.com` | Texto con enlace |
| Cualquier otro | Tarjeta adaptable para un webhook de Teams Workflows |

El enlace lleva a la vista que corresponde: gestión de hallazgos, Administración o historial de costos.

## Deduplicación y reintentos

- La marca de agua es el `until` de la última ejecución correcta de `notify`. La primera vez solo mira las últimas 26 h, para no vaciar la historia completa en el canal.
- Los avisos de costo no son transiciones: sus claves vigentes quedan en `detail.sent` y no se repiten mientras sigan vigentes.
- Si el webhook falla, el paso queda en error sin mover la marca, y el día siguiente reintenta lo mismo.
- Sin webhook configurado, el paso queda `parcial` y no marca nada como enviado.
- La URL del webhook es una credencial: va como secreto de Container Apps y los errores solo muestran el host.

## Reporte ejecutivo mensual

Desde el día 4 de cada mes, el paso `report` envía el reporte del mes anterior una sola vez. Contenido:

- gasto del mes contra el mes anterior y contra el presupuesto de cada nube, con las cuentas y servicios de más gasto;
- hallazgos abiertos por severidad, detectados y resueltos en el mes, y la lista de críticos y altos;
- recursos activos por nube, cobertura de Terraform, nuevos y eliminados en el mes;
- ejecuciones del job en el mes y su resultado.

El PDF se genera sin dependencias externas ([`app/reports/pdf.py`](../../backend/app/reports/pdf.py)): una librería de PDF traería Pillow y sus avisos de Trivy a la imagen. En el panel, Reportes → *Reporte ejecutivo mensual* descarga el de cualquier mes.

## Configuración

| Variable de Terraform | Variable de entorno | Para qué |
|---|---|---|
| `notify_webhook_url` (sensible) | `NOTIFY_WEBHOOK_URL` | Destino de avisos y reporte |
| `monthly_budgets_usd` | `MONTHLY_BUDGETS_USD` | Presupuesto por nube (`azure=5,aws=5`) |

Antes de un `terraform apply`, exporta `TF_VAR_notify_webhook_url`; sin ella, el apply borra el secreto del webhook.

## Pendiente

Correo como canal y enrutamiento por severidad o por cuenta (ver [pendientes](../roadmap.md#fase-3-lo-que-falta)).

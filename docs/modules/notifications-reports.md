# Avisos y reportes

La plataforma avisa sola en un canal de Discord, Slack o Teams y envía un reporte ejecutivo cada mes. Los dos son los últimos pasos del [job diario](../flows.md#job-diario-de-recolección) y usan el mismo webhook (`NOTIFY_WEBHOOK_URL`).

## Eventos

| Evento | Cuándo | Se repite |
|---|---|---|
| `finding.opened` | Un hallazgo de severidad alta o crítica se detecta, se reabre o vence su aceptación, y sigue abierto | No: solo existe en la transición |
| `collector.failed` | Las dos últimas ejecuciones de un recolector fallaron | Cada día mientras siga caído (es un recordatorio) |
| `resource.unmanaged_created` | Apareció un recurso que ningún estado de Terraform contiene y que creó una persona según Activity Log o CloudTrail; el aviso dice quién | No: solo cuenta lo aparecido desde el último aviso |
| `cost.anomaly` | En los últimos 3 días completos, una cuenta gastó más que la media de los 14 días previos + 3 desviaciones, o más del doble; mínimo 0,50 USD | No: clave `anomalia:{cuenta}:{día}` |
| `budget.threshold` | El gasto del mes de una nube llega al 80 % o al 100 % de su presupuesto (*Plataforma → Ajustes → Costos*; `MONTHLY_BUDGETS_USD` es el valor inicial), o desde el día 8 el pronóstico lineal lo supera | No: clave `presupuesto:{nube}:{mes}:{nivel}` |

Los avisos de Kubernetes (incidencias de clúster y agente sin reportar) salen del job `k8s-watch` cada 10 minutos, al mismo webhook: ver [Kubernetes](kubernetes-sre.md#avisos).

Para `resource.unmanaged_created`, un recurso sin estados de Terraform conectados (cobertura desconocida) o creado por una automatización (Terraform, un pipeline, un servicio de la nube) no cuenta, ni el inventario de una cuenta recién conectada. Si el creador se conoce recién días después de que el recurso apareció, ese recurso no se avisa.

Un día sin filas de costo cuenta como 0: pasar de nada a gastar también es anomalía. El presupuesto se configura en Terraform (`monthly_budgets_usd`, por ejemplo `{ azure = 5, aws = 5 }`).

## Motor de avisos

Todo lo que la plataforma publica en el canal pasa por un solo motor ([`core/avisos.py`](../../backend/app/core/avisos.py)): los avisos diarios, `k8s-watch`, los incidentes, el reporte mensual y el resumen semanal. Cada emisor arma su mensaje y lo publica con su dominio, tipo, severidad y una clave. El motor:

1. aplica los [silencios](incidents.md#silencios) cuando el aviso dice a qué clúster, namespace, alerta u objeto se refiere;
2. descarta un duplicado (la misma clave enviada hace menos de `deduplicar_min`, 10 por defecto);
3. arma el mensaje del canal (el PDF adjunto solo en Discord) y lo envía;
4. deja cada aviso en el registro (`DATA_DIR/avisos/AAAA-MM.jsonl`, sin abrir la base), visible en *Operación → Avisos* con su resultado: enviado, silenciado, duplicado o fallido.

**Qué llega al canal.** En *Plataforma → Ajustes → Avisos*, cada dominio tiene su **severidad mínima** (por defecto `info`, todo): lo de menor severidad no se envía y queda en el registro como *filtrado*. Un **silencio** con solo el campo *alerta* calla un tipo de aviso entero, en todos los clústeres: `resumen_semanal`, `atencion_diaria`, `reporte_mensual`, `kubernetes`, `incidente`. Varios canales (por severidad o dominio a distintos webhooks) quedan para cuando haya un segundo canal: cada URL es un secreto más en Azure.

**Modo registro.** Arranca en `registro`: envía todo exactamente como antes y solo anota lo que habría silenciado o descartado. Después de una semana revisando *Operación → Avisos*, se pasa a `activo` en *Plataforma → Ajustes → Avisos* (puerta de la fase 2 del [plan 10](../plan/10-reestructuracion-por-dominios.md)).

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

Desde el día 4 de cada mes, el paso `report` envía el reporte del mes anterior una sola vez, con todos los bloques y narrado si hay modelo. Bloques (`BLOQUES` en [`app/reports/mensual.py`](../../backend/app/reports/mensual.py)):

| Bloque | Contenido |
|---|---|
| `costos` | Gasto del mes contra el mes anterior y contra el presupuesto de cada nube, con las cuentas y servicios de más gasto |
| `seguridad` | Hallazgos abiertos por severidad, detectados y resueltos en el mes, y la lista de críticos y altos |
| `inventario` | Recursos activos por nube, cobertura de Terraform, nuevos y eliminados en el mes |
| `incidentes` | Incidentes del mes por severidad, resueltos y su mediana en minutos, cerrados como ruido, diagnósticos marcados y correctos, y los principales |
| `plataforma` | Ejecuciones del job en el mes y su resultado |

**Narrado**: con `narrar=true` (o en el envío del job, si hay modelo) la IA escribe dos o tres frases ejecutivas por bloque con las mismas cifras del reporte (`reportes.narrar`, JSON por bloque, datos delimitados como no confiables). Van en gris bajo el título de cada bloque, con una nota al pie de que las redactó la IA. Si el modelo falla, el reporte sale igual sin narración. El caso *reporte mensual narrado* de `eval.dominios` vigila que no invente cifras.

`GET /api/reports/monthly?month=AAAA-MM&bloques=costos,incidentes&narrar=true` (rol Lector; narrar descuenta el cupo del modelo). En el panel, *Plataforma → Reportes → Reporte ejecutivo mensual* elige el mes, los bloques y la narración.

El PDF se genera sin dependencias externas ([`app/reports/pdf.py`](../../backend/app/reports/pdf.py)): una librería de PDF traería Pillow y sus avisos de Trivy a la imagen.

## Resumen semanal

En la primera corrida del job de cada semana ISO (los lunes a las 06:00 UTC, en régimen normal), el paso `weekly` ([`collectors/semanal.py`](../../backend/app/collectors/semanal.py)) junta las cifras de los 7 días cerrados anteriores y las publica en el canal:

- Gasto contra la semana anterior y los tres servicios que más gastaron. Los costos llegan con hasta 72 h de retraso, y el resumen dice hasta qué fecha hay datos.
- Hallazgos nuevos y resueltos en la semana, y los críticos y altos abiertos hoy.
- Incidentes: cuántos hubo, cuántos siguen abiertos, mediana para resolver, cuántos se cerraron como ruido y la precisión del diagnóstico según las marcas del panel.
- Recursos nuevos (y cuántos fuera de Terraform) y borrados.
- Salud del job: pasos bien y con error.

El modelo (Gemini, la misma clave del API como secreto del job) lo redacta como un resumen ejecutivo con 1 o 2 acciones para la semana, usando solo esas cifras. Sin modelo, o si falla, sale con las cifras tal cual. La semana enviada queda en `detail.sent` del paso y no se repite. Hace falta al menos una semana de historia propia.

## Configuración

| Variable de Terraform | Variable de entorno | Para qué |
|---|---|---|
| `notify_webhook_url` (sensible) | `NOTIFY_WEBHOOK_URL` | Destino de avisos y reporte |
| `monthly_budgets_usd` | `MONTHLY_BUDGETS_USD` | Presupuesto por nube (`azure=5,aws=5`) |

Antes de un `terraform apply`, exporta `TF_VAR_notify_webhook_url`; sin ella, el apply borra el secreto del webhook.

## Pendiente

Correo como canal y enrutamiento por severidad o por cuenta (ver [pendientes](../roadmap.md#fase-3-lo-que-falta)).

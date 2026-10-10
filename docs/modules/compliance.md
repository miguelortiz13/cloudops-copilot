# Cumplimiento

Qué controles de **CIS Microsoft Azure Foundations Benchmark 2.0.0** y de **ISO/IEC 27001:2022 (Anexo A)** evidencia la plataforma, en qué estado están, el catálogo de reglas que los evalúa y la clasificación ISO de los activos de información.

Todo sale de la base de datos que llena el [recolector diario](../adr/0007-almacen-de-datos-y-recolectores.md); el panel lo lee de la vista precalculada, sin despertar Azure SQL. Reemplaza a la hoja `12_inventario_iso` del Excel del pipeline y a `/api/governance/iso`.

## Catálogo de reglas

`backend/app/compliance/catalog.py` es la única definición de cada regla. De ahí la toman:

- el recolector, que la sincroniza en la tabla `rules` en cada ejecución;
- `SecOpsService`, para el título, la recomendación y los controles de los hallazgos en vivo;
- el panel (pestañas **Controles** y **Catálogo de reglas**).

Cada regla tiene un identificador estable, una severidad por defecto (el recolector la sube según la exposición real), una descripción del riesgo, cómo se detecta, cómo corregirlo, referencias y los controles que evidencia.

| Regla | CIS 2.0.0 | ISO 27001:2022 |
|---|---|---|
| `network.admin-port-open` (RDP/SSH desde internet) | 6.1, 6.2 | A.8.20, A.8.22* |
| `storage.public-blob-access` | 3.7 | A.5.15, A.8.3, A.8.12* |
| `secrets.vault-public-network` | 8.7 | A.8.20, A.8.24* |
| `database.public-network` | 4.1.2* | A.8.20, A.8.3* |
| `web.https-not-enforced` | 9.2 | A.5.14, A.8.24* |
| `storage.disk-without-cmk` | 7.3, 7.4 | A.8.24 |
| `platform.provisioning-failed` | — | A.8.9 |

\* **Evidencia parcial**: la regla comprueba una parte o una condición relacionada. Por ejemplo, `database.public-network` mira si el endpoint público está habilitado, pero no el contenido de las reglas de firewall que pide CIS 4.1.2. Una evidencia parcial nunca se presenta como directa.

La numeración de CIS cambia entre versiones; se usa la 2.0.0 porque es la que Azure Policy publica como iniciativa integrada. Una prueba (`catalog.validar()`) impide citar un control que no esté en el catálogo de controles o dejar un control sin evidencia.

### Agregar una regla

1. La consulta KQL en `services/kql.py` y su tipo en `SecOpsService.build_report`.
2. La entrada en `REGLAS` y `CONSULTA_DE_TIPO` de `catalog.py`, con sus controles. Si cita un control nuevo, agregarlo a `_CONTROLES`.
3. La prueba `test_el_catalogo_es_coherente` falla si algo quedó sin enlazar.

No hace falta migración: el recolector inserta la regla en la siguiente ejecución.

## Estado de un control

El estado es el peor de su evidencia:

| Estado | Cuándo |
|---|---|
| No cumple | Alguna regla tiene hallazgos abiertos o asumidos (o, en A.5.9 y A.5.12, hay activos sin clasificar o sin custodio) |
| Sin evidencia | Alguna regla no se pudo evaluar en la última recolección (su consulta falló) o el recolector no ha corrido |
| Riesgo aceptado | Solo quedan hallazgos aceptados con vencimiento vigente |
| Cumple | Todas sus reglas se evaluaron y no hay hallazgos activos |

Una consulta fallida nunca se lee como "cumple": es la misma regla que impide que un hallazgo se dé por resuelto sin evidencia.

**Cobertura.** El panel lista solo los controles que alguna regla evidencia (8 de CIS y 10 de ISO) y lo dice. No es un puntaje de certificación ni un porcentaje sobre el marco completo.

## Clasificación de activos (A.5.9, A.5.12)

El paso `classification` del recolector (después del inventario) clasifica cada recurso activo con una regla explicable (`app/compliance/classification.py`):

| Ambiente (tag `Environment`) | Guarda datos o llaves | Cómputo o red expuesta | Resto |
|---|---|---|---|
| Producción | Confidencial (3·3·3) | Restringido (2·3·3) | Restringido (2·2·2) |
| Otro o sin declarar | Restringido (2·2·2) | Uso interno (1·1·1) | Uso interno (1·1·1) |

- **Datos o llaves:** SQL, Key Vault, Storage, Cosmos DB, PostgreSQL, MySQL y Redis.
- **Cómputo o red expuesta:** AKS, máquinas virtuales, App Service y Functions, NSG y Container Apps.
- **Criticidad:** la suma de confidencialidad, integridad y disponibilidad (de 3 a 9). Todo activo de producción requiere análisis de riesgo.
- **Custodio:** la primera tag de propietario con valor útil (las mismas claves que usa gobernanza); si no hay, quien creó el recurso según el registro de actividad.

Cada clasificación guarda el motivo con el que se decidió ("Producción · guarda datos o llaves").

### Clasificación manual

Un **operador** puede fijar la clasificación, la tríada, el análisis de riesgo y el custodio desde el detalle del activo, con un motivo obligatorio. El recolector respeta una clasificación manual hasta que alguien la devuelve a la automática. Ambas acciones quedan en la auditoría (`activo.clasificacion` y `activo.clasificacion_automatica`).

### Exportación

**Exportar CSV** descarga el inventario clasificado (UTF-8 con BOM, para que Excel respete las tildes), con el motivo, el método, quién lo actualizó y los hallazgos activos de cada activo.

## API

| Método | Ruta | Rol | Descripción |
|---|---|---|---|
| `GET` | `/api/compliance` | Lector | Marcos con el estado de cada control y su evidencia, y el catálogo de reglas con sus conteos |
| `GET` | `/api/compliance/assets` | Lector | Activos con su clasificación, custodio y hallazgos activos, y resumen |
| `GET` | `/api/compliance/assets/export` | Lector | El mismo inventario en CSV |
| `POST` | `/api/compliance/assets/classification` | Operador | Clasificación manual (`classification`, `confidentiality`, `integrity`, `availability` de 1 a 3, `risk_required`, `reason`, `custodian`) |
| `POST` | `/api/compliance/assets/classification/restore` | Operador | Vuelve a la clasificación automática |

Sin base de datos responden 503.

## Modelo de datos

- `rules`: además del título, la severidad y la remediación, `frameworks` (`{"cis-azure-2.0.0": [{"control": "6.1", "match": "directa"}], ...}`), `description`, `detection` y `reference_urls`.
- `asset_classifications`: una fila por recurso, con la clasificación, la tríada, el análisis de riesgo, el custodio, el método (`automatica` o `manual`), el motivo y quién la actualizó y cuándo.

Migración `0003_cumplimiento`.

## Límites

- Las reglas son detectivas: dicen qué incumple hoy, no impiden que ocurra. Pasar a reglas preventivas (Azure Policy) es la fase 4 ("Políticas como código").
- El control A.5.13 (etiquetado de la información) no se evalúa todavía: requiere una tag de clasificación acordada.
- Cada regla es una consulta de Resource Graph con el rol Reader; no usa Defender for Cloud.

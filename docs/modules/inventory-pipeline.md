# Pipeline de inventario

Código: [`backend/pipelines/inventory`](../../backend/pipelines/inventory).

Proceso por lotes que exporta el inventario de Azure a un **Excel maestro** versionado. Complementa al panel (que es en vivo) con algo que el panel no tiene: un registro acumulado donde el equipo anota revisiones manuales —custodio confirmado, módulo de Terraform candidato, prioridad de adopción— que sobreviven a cada nueva extracción.

## Ejecución

- Desde el panel: botón **Sincronizar** (`POST /api/sync`), con log en vivo en `/api/sync/status`.
- Desde la línea de comandos:

```bash
cd backend
DATA_DIR=./data bash pipelines/inventory/weekly_inventory.sh
```

Al terminar, si hay una conversación de Teams registrada o `TEAMS_WEBHOOK_URL`, envía un resumen (nuevos, eliminados, total, cumplimiento de tags).

## Pasos

| # | Script | Qué hace |
|---|---|---|
| 0 | `bootstrap_workbook.py` | Crea el Excel maestro vacío si no existe (nunca toca uno existente) |
| 1 | `export_all.py` | Ejecuta las consultas de `queries/*.kql` contra Resource Graph (paginación completa) y guarda JSON en `raw/` y CSV en `exports/` |
| 2 | `update_excel.py` | Actualiza las hojas de resumen desde los CSV, sin tocar el master |
| 3 | `sync_master.py` | Sincroniza campos mutables (tags, grupo, región) y mueve los eliminados a `13_historical_backup` |
| 4 | `enrich_master.py` | Agrega recursos nuevos con dominio y subdominio |
| 5 | `finalize_master.py` | Rellena módulo candidato, prioridad de adopción y si requiere `terraform import` |
| 6 | `tags_enrich.py`, `fix_owner_pm.py`, `normalize_classify.py` | Custodio, ambiente, fuente de evidencia, drift; matriz de priorización |
| 7 | `provisioning_classify.py`, `classify_assets_iso.py` | Método de aprovisionamiento inferido; clasificación ISO 27001 |
| 8 | `weekly_snapshot.py` | Copia versionada en `snapshots/` y hoja de trazabilidad con el diff contra la semana anterior |

## Estructura del Excel

| Hoja | Contenido |
|---|---|
| `09_analysis_master` | Registro maestro, una fila por recurso. **Protegida**: los pasos solo agregan o completan, no borran revisiones manuales |
| `10_trazabilidad` | Altas y bajas respecto al snapshot anterior |
| `11_matriz_priorizacion` | Prioridad de adopción de IaC por dominio y ambiente |
| `12_inventario_iso` | Activos con triada C-I-D y puntuación. El panel ya no la lee: la clasificación vive en la base ([cumplimiento](compliance.md)) |
| `13_historical_backup` | Recursos eliminados de Azure |

## Clasificación ISO 27001

Para los controles 5.9 (inventario de activos), 5.12 (clasificación) y 5.13 (etiquetado), cada activo recibe una calificación de **Confidencialidad**, **Integridad** y **Disponibilidad** (1-3) según su tipo y ambiente, una puntuación agregada (3-9), una clasificación (Uso Interno, Restringido, Confidencial...) y la marca de si requiere análisis de riesgo (activos críticos en producción).

## Datos

Todo se escribe en `DATA_DIR`: `raw/`, `exports/`, `snapshots/` y el Excel. El código del pipeline no guarda nada en su propia carpeta. Estos archivos contienen el inventario real del tenant y **están excluidos de git**.

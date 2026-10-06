# Inventario y gobernanza

Código: [`services/inventory_service.py`](../../backend/app/services/inventory_service.py), [`services/governance.py`](../../backend/app/services/governance.py), [`services/history_service.py`](../../backend/app/services/history_service.py), [`routers/inventory.py`](../../backend/app/routers/inventory.py).

## Qué ofrece

- Inventario multi-suscripción en tiempo real desde Azure Resource Graph, con paginación por `skip_token` (supera el límite de 1.000 filas por consulta).
- KPIs: total de recursos, suscripciones, grupos, regiones, recursos no conformes, candidatos a Shadow IT, sin custodio, producción vs. no producción.
- Matriz de cumplimiento de las tags obligatorias (`MANDATORY_TAGS`).
- Tabla de recursos con filtros (texto, grupo, tipo, región, ambiente, tag faltante, solo no conformes, solo Shadow IT) y panel de detalle con completitud de datos (0-100 %).
- Evolución histórica diaria de los KPIs.
- Creaciones manuales con evidencia del historial de cambios.
- Exportación a CSV.

## KPIs agregados en Azure

Los KPIs, la matriz de tags y la paginación se resuelven con **agregados de Resource Graph** en lugar de descargar el inventario para contarlo en memoria:

| Inventario | Descargando todo | Agregado en Azure |
|---|---|---|
| ~600 recursos | 1,3 s | 1,3 s |
| ~3.700 recursos | ~7,7 s | ~1,3 s |
| ~10.000 recursos | ~21,9 s | ~1,3 s |

El cuello de botella medido es la **transferencia** (~2 ms por recurso), no el conteo: normalizar 10.000 recursos en Python toma 0,1 s. El punto de equilibrio está alrededor de 580 recursos.

La equivalencia entre ambos caminos (KQL y Python) la verifica `tests/integration/test_inventory_kpis.py` contra un tenant real: diez KPIs escalares, cuatro distribuciones, la matriz de tags y seis casos de paginación y filtros. La implementación en memoria se conserva como referencia (`get_summary_from_resources`) y como respaldo si Resource Graph falla.

> **No modifiques la lógica de tags o Shadow IT sin volver a correr esa prueba** (`make test-integration`).

## Regla de Shadow IT

Un recurso es **candidato** a Shadow IT solo cuando se cumplen **cuatro ausencias** a la vez:

1. Sin evidencia de IaC en las tags (claves como `managedby`, `iac`, `provisioning_method`... o valores como `terraform`, `bicep`, `pulumi`).
2. No es derivado de otro recurso (`managedBy` vacío, no está en grupos `MC_*`/`databricks-rg*`, no es un tipo que Azure crea solo).
3. Sin custodio identificable (`owner`, `team`, `ownertech`, `createdby`...).
4. Con las tags obligatorias incompletas.

Además, si el recurso aparece en un estado de Terraform (ver [IaC](iac.md)), queda exonerado.

### Por qué cuatro señales

Una versión anterior bastaba con que faltara la tag de IaC y el campo `managedBy`. Medido en un tenant real de ~600 recursos, eso señalaba **el 90 %** del inventario, y la mayoría tenían todas las tags obligatorias: se les acusaba solo por no tener `managedBy`, un campo que Azure rellena únicamente cuando otro recurso es dueño del primero. Un panel que señala el 90 % no dirige ninguna acción. Con la regla de cuatro señales quedan alrededor del **6 %**, y la muestra son justo los que delatan el portal: VNets con nombres autogenerados, NSG `basicNsg...`, extensiones de VM y reglas de autoescalado sueltas.

## Evidencia frente a heurística

Ninguna regla sobre tags puede *demostrar* que algo se creó a mano; solo constata que nadie lo declaró. La tabla `resourcechanges` de Resource Graph sí registra qué identidad creó cada recurso: una cuenta con `@` es una persona en el portal o la CLI; un GUID es automatización. `/api/inventory/manual-creations` devuelve esa lista **declarando siempre la ventana observada**, porque Azure conserva esos eventos unos catorce días.

## Evolución histórica

Cada consulta del resumen registra un punto diario en `DATA_DIR/kpi_history` (JSON Lines, ~300 bytes por día y scope). El panel muestra la evolución del cumplimiento de tags, los no conformes y el Shadow IT con el delta del período. La serie **se acumula desde la primera ejecución**: no reconstruye el pasado, y mientras no haya al menos dos días la interfaz lo dice en lugar de dibujar una línea vacía.

## Configuración relevante

`MANDATORY_TAGS`, `INVENTORY_CACHE_TTL_SECONDS`, `AZURE_ALLOWED_SUBSCRIPTIONS`, `DATA_DIR`. Ver [configuration.md](../configuration.md).

# 0008 · FOCUS como modelo de costos

**Estado:** propuesta (fases 1 y 2 del [plan de evolución](../plan/README.md))

## Contexto

Unificar costos de varias nubes exige un esquema común. Diseñar uno propio implica mantener traducciones por proveedor y discutir semánticas (precio de lista, con descuento, amortizado). Además, las APIs de consulta son caras o limitadas: Cost Explorer cobra USD 0,01 por petición paginada y Cost Management responde 429 con facilidad.

## Decisión

Usar **FOCUS** (FinOps Open Cost and Usage Specification) como modelo canónico de costos y alimentarlo con los **exports** de cada nube, que ya lo producen:

- Azure: exports de Cost Management en formato FOCUS a una cuenta de almacenamiento.
- AWS: Data Exports CUR 2.0 / FOCUS a S3, consultado con Athena.
- GCP (fase 4): billing export a BigQuery con su vista FOCUS.

Las APIs de consulta quedan como respaldo para los días que el export aún no trae.

## Consecuencias

- La suma de varias nubes usa columnas con el mismo significado (`BilledCost`, `EffectiveCost`, `ServiceName`, `ChargePeriodStart`).
- Historia de meses sin agotar cuotas de API.
- El primer export tarda hasta un día en llegar; el panel lo declara.
- Se adopta un estándar mantenido por la FinOps Foundation en lugar de un esquema propio.

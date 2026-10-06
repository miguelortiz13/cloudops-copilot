# 0005 · KPIs agregados en Resource Graph

**Estado:** aceptada

## Contexto

El resumen de inventario descargaba todos los recursos y los contaba en Python. El tiempo crecía linealmente con el tenant: ~1,3 s con 600 recursos, ~7,7 s con 3.700, ~22 s estimados con 10.000. El cuello de botella medido era la transferencia (~2 ms por recurso), no el cómputo (0,1 s para normalizar 10.000).

## Decisión

Calcular KPIs, distribuciones, matriz de tags y paginación con `summarize` y paginación de Resource Graph. Conservar la implementación en memoria como referencia y como respaldo si la consulta agregada falla.

## Consecuencias

- El tiempo de respuesta es ~1,3 s independientemente del tamaño del tenant.
- La semántica de Python (comparación de tags sin mayúsculas, valores que no cuentan como presentes) debe replicarse exactamente en KQL. `tests/integration/test_inventory_kpis.py` compara ambos caminos contra un tenant real y es obligatoria antes de cambiar reglas de tags o Shadow IT.

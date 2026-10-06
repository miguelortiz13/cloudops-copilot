# Costos (FinOps)

El módulo tiene dos pestañas, en este orden a propósito: primero **cuánto se gasta y en qué**, después **cómo ahorrar**. Una oportunidad de 3 USD solo se puede juzgar sabiendo si la cuenta es de 30 o de 30.000.

## Visión general de costos

Código: [`services/cost_overview_service.py`](../../backend/app/services/cost_overview_service.py), endpoint `GET /api/finops/costs`, vista [`CostsView.tsx`](../../frontend/src/modules/finops/CostsView.tsx).

| Bloque | Qué muestra | Fuente |
|---|---|---|
| Cifra principal | Gasto de los últimos 30 días y variación frente a los 30 anteriores | Serie diaria |
| Mes en curso | Facturado desde el día 1 y proyección lineal de cierre (promedio de los últimos 7 días) | Serie diaria |
| Evolución diaria | 60 días en columnas: el periodo actual en acento y el anterior en gris como contexto; vista de tabla equivalente | Serie diaria |
| Distribución | Por servicio, grupo de recursos, suscripción o región | Gasto por recurso |
| Atribución por etiqueta | Showback por cada tag de `SHOWBACK_TAGS` y porcentaje sin etiquetar | Gasto por recurso + tags |
| Recursos con mayor gasto | Los 25 más costosos con su peso sobre el total; los ya eliminados que facturaron en la ventana se marcan | Gasto por recurso + inventario |

No lanza consultas nuevas por recurso: reutiliza la caché de `CostService` (gasto por recurso a 30 días y serie diaria), que la precarga mantiene caliente. Los cargos que no pertenecen a ningún recurso (soporte, Marketplace, reservas) se declaran aparte en lugar de esconderse. Todas las cifras son facturación real; las suscripciones sin cobertura se nombran y quedan fuera del total, sin rellenar con estimaciones.

## Optimización y ahorro

Código: [`services/finops_service.py`](../../backend/app/services/finops_service.py), [`services/cost_service.py`](../../backend/app/services/cost_service.py), [`services/metrics_service.py`](../../backend/app/services/metrics_service.py), [`services/pricing.py`](../../backend/app/services/pricing.py).

### Qué ofrece

| Capacidad | Fuente |
|---|---|
| Recursos huérfanos: discos sin adjuntar, IPs públicas libres, NICs sin VM, App Service Plans vacíos, snapshots antiguos | Resource Graph |
| Ahorro calculado sobre la **factura real** de cada huérfano (últimos 30 días) | Cost Management por `ResourceId` |
| Showback/chargeback por tag (`SHOWBACK_TAGS`), con fila explícita *sin atribuir* | Cost Management + tags |
| Anomalías: media diaria de los últimos 7 días vs. los 23 anteriores, y picos > 2× el promedio | Cost Management |
| Presupuestos con consumo y pronóstico reales | Consumption API |
| Right-sizing con CPU promedio real a 30 días | Azure Monitor |
| Puntos ciegos: recursos sin tags para asignación de costos | Resource Graph |

### Procedencia de las cifras

El reporte nunca presenta una estimación como factura:

- `cost_data.basis` tiene tres estados: `actual` (todas las suscripciones del scope medidas), `partial` (algunas) y `estimated` (ninguna).
- `cost_data.coverage` enumera qué suscripciones aportaron factura y cuáles no, **distinguiendo la falta de permiso de un fallo transitorio**: lo primero se resuelve asignando un rol; lo segundo, reintentando.
- La decisión real/estimado se toma **por recurso**, según su suscripción.
- Las estimaciones usan la tabla única de `pricing.py`.

En el panel se ve como una banda de "Cobertura parcial — N de M suscripciones" con la lista de las que quedaron fuera.

### Permisos

Para consultas de costo con alcance de suscripción, `Reader` basta. `Cost Management Reader` solo hace falta para alcances superiores (management group, billing account) o si la organización restringe la visibilidad de cargos. Las suscripciones que responden `403` se recuerdan `COST_DENIAL_TTL_SECONDS` (1 h): al expirar se vuelven a probar, así que **otorgar el rol se detecta sin redesplegar**.

### El límite de tasa es la restricción real

El reporte necesita del orden de dos consultas a Cost Management por suscripción. Con ~30 suscripciones son ~60 llamadas contra una API que responde `429` con facilidad. Tres medidas lo resuelven:

1. **Precarga en segundo plano** (`COST_WARM_*`): una suscripción cada 9 s, y una segunda pasada al doble de lento sobre las que fallaron. Las peticiones interactivas leen de caché y nunca esperan a la API.
2. **Caché persistente** en `DATA_DIR/cost_cache`, con escritura atómica. Un despliegue ya no vacía la caché ni gasta la cuota de nuevo; mientras siga vigente, la precarga se salta el ciclo. Las denegaciones (`403`) no se persisten a propósito.
3. **Consultar a nivel de management group no es la salida**: en la práctica la consulta está autorizada y responde, pero puede devolver cero filas mientras las suscripciones individuales sí tienen cargos. La consulta por suscripción sigue siendo necesaria.

Pruebas: `test_finops_coverage.py`, `test_cost_cache_persistente.py`, `test_cost_warm_retry.py`, `test_chat_cost_coherence.py`.

Decisión registrada en [ADR 0003](../adr/0003-cache-de-costos-persistente.md).

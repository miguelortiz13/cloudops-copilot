# 0006 · Abstracción de proveedores de nube

**Estado:** aceptada, en implementación (fase 1 del [plan de evolución](../plan/README.md)). Hecho: `AzureClient` extraído del agente; contrato en `app/providers/base.py` con `AzureProvider` y un proveedor en memoria, verificados por la misma batería de contrato (`tests/contract/`); los recolectores del modelo canónico (inventario, costos, hallazgos) ya solo hablan con el proveedor. Pendiente: llevar las vistas en vivo y el chat a la capa, y `KubernetesProvider`.

## Contexto

Azure está en todas las capas: los servicios reciben ids de suscripción, `subscription_of()` asume ids `/subscriptions/...`, las reglas son KQL de Resource Graph y el agente mezcla el cliente de Azure con el chat. Añadir AWS sobre esa base obligaría a duplicar cada servicio y cada regla, y rompería el principio de una definición por regla ([ADR 0002](0002-una-definicion-por-regla.md)).

## Decisión

Introducir una capa `app/providers/` con interfaces por capacidad (`InventoryProvider`, `CostProvider`, `SecurityProvider`, `IacStateProvider`, `ActivityProvider`, `KubernetesProvider`) y una implementación por nube. Todas devuelven un **modelo canónico** con identificador universal (`uid`), tipo canónico y procedencia.

Las reglas se definen una vez en un catálogo por capacidad (`storage.public-access`) y cada proveedor implementa su evaluación. Un proveedor declara qué capacidades soporta; lo que no soporta se muestra como "no disponible", nunca como cero.

## Consecuencias

- El resto del sistema (API, recolectores, panel, agentes) no conoce KQL, ARN ni SDK de ninguna nube.
- La primera tarea es extraer `AzureProvider` sin cambiar comportamiento; las pruebas de contrato y la prueba de fidelidad KQL lo verifican.
- Cada nube nueva es una implementación más, con sus pruebas de contrato sobre respuestas grabadas: una fábrica en `tests/contract/proveedores.py` y la misma batería (`test_contrato.py`) sin cambios.
- Lo propio de una nube vive en su proveedor y no en los recolectores: en Azure, el uid de las reglas de NSG, qué consulta KQL evidencia cada regla y el reintento ante el 429 de Cost Management.
- Hay un costo de indirección: una capacidad muy específica de una nube necesita un lugar en la interfaz o queda como extensión del proveedor.

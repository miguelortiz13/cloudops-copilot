# 0002 · Una sola definición por regla de dominio

**Estado:** aceptada

## Contexto

Las reglas —qué es un disco huérfano, un Key Vault expuesto, un recurso gestionado por IaC, cuánto cuesta un recurso— estaban escritas varias veces: en el servicio del panel, en el contexto del chat y en el motor de reglas. Habían divergido. Sobre el mismo tenant, el panel contaba 112 cuentas de almacenamiento públicas y el chat 354; la cobertura de IaC tenía tres cifras distintas según dónde se preguntara; una IP pública costaba 3,60 en un sitio y 3,65 en otro; y el chat publicaba estimaciones bajo una clave llamada "costo real".

## Decisión

Cada regla vive en un único módulo y todos los consumidores la importan:

| Módulo | Reglas |
|---|---|
| `services/governance.py` | IaC, custodio, recursos derivados, Shadow IT, tags obligatorias en KQL |
| `services/kql.py` | Consultas de dominio |
| `services/pricing.py` | Tarifas de referencia |
| `services/cost_service.attach_costs()` | Atribución de costo y su procedencia |
| `core/config.py` | Esquema de tags de la organización |

El agente no consulta por su cuenta: recibe los servicios del panel (`attach_services`).

## Consecuencias

- Panel, reportes y chat dan las mismas cifras; si no, es un bug con un único lugar donde corregirlo.
- Las reglas en Python tienen su equivalente en KQL en el mismo archivo, y una prueba de integración verifica que coincidan.
- Añadir una regla exige ubicarla en el módulo correcto, no en el servicio que la necesita primero.

# 0003 · Precarga y caché persistente de costos

**Estado:** aceptada

## Contexto

Cost Management consolida el gasto una vez al día y limita la tasa con dureza. El reporte de FinOps necesita del orden de dos consultas por suscripción: con ~30 suscripciones, ~60 llamadas que la API corta con `429`. Medido: consultando bajo demanda, el usuario esperaba y recibía cobertura parcial; con la caché solo en memoria, cuatro despliegues en dos horas agotaron la cuota y la cobertura cayó de 24 a 9 suscripciones durante horas.

Consultar a nivel de management group no sirvió: la API respondía `200` con cero filas mientras las suscripciones individuales tenían cargos.

## Decisión

1. Un hilo en segundo plano precarga el costo **una suscripción cada 9 s**, con una segunda pasada al doble de lento sobre las que fallaron. Las peticiones interactivas leen de caché.
2. La caché se **persiste en `DATA_DIR`** (File Share en Azure) con escritura atómica, y la precarga se salta el ciclo mientras siga vigente.
3. Las denegaciones (`403`) **no** se persisten: se recuerdan una hora en memoria para que un permiso recién otorgado se detecte solo.

## Consecuencias

- El panel responde desde caché y el costo tiene hasta 6 h de antigüedad, coherente con la consolidación diaria de Cost Management.
- Los reinicios y despliegues no consumen cuota.
- Se depende de un almacenamiento persistente; sin él la plataforma funciona, pero cada arranque vuelve a precargar.

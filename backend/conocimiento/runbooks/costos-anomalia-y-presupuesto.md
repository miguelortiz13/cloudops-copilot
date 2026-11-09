# Runbook: gasto anómalo o presupuesto en riesgo

Avisos: *Gasto anómalo* (el gasto de un día muy por encima de su media) y *Presupuesto al 80 % / 100 % / con pronóstico de superarse*. Aparecen en *Costos → Alertas de costo*.

## Gasto anómalo: diagnóstico

1. Abrir la alerta y pedir **Explicar con IA**: compara el día contra la media por servicio y por recurso y nombra los recursos nuevos de ese día con quién los creó.
2. El patrón más común es un recurso nuevo caro (una VM con GPU, un clúster, un SKU alto) creado a mano y fuera de Terraform.
3. Otro patrón: un recurso existente que cambió de tamaño o empezó a transferir datos (Bandwidth).
4. Revisar *Activos → Recursos* filtrando por los nuevos y por *fuera de Terraform*.

## Gasto anómalo: resolución

- Recurso de prueba olvidado: confirmar con quien lo creó y borrarlo; marcar la alerta como resuelta.
- Gasto legítimo (una carga nueva planificada): marcar la alerta como *descartada* con una nota; si va a seguir, ajustar el presupuesto en *Plataforma → Ajustes → Costos*.
- Si se aplica una baja, registrarla como ahorro en *Costos → Ahorro* para que se verifique sola.

## Presupuesto en riesgo

1. Ver en *Costos → Gasto* qué cuentas y servicios explican el mes y el pronóstico.
2. Buscar oportunidades en *Costos → Ahorro* (recursos sin uso, discos huérfanos, IPs sin asociar).
3. Si el presupuesto quedó corto para un gasto aprobado, subirlo en ajustes (queda en el historial con quién lo cambió).

## Export de costos vacío

La alerta *export vacío* significa que el export de costos entrega archivos sin filas: revisar el export en la nube (alcance, formato, ruta) y la tabla de Glue o el contenedor de Azure. Sin filas, los costos del panel se quedan atrás.

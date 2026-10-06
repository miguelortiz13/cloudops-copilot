# 0004 · Los estados de Terraform exoneran, pero no acusan

**Estado:** aceptada

## Contexto

La cobertura de IaC se medía por tags (`provisioning_method = terraform`, etc.). Las tags miden cuántos equipos etiquetan, no cuánta infraestructura está codificada: en un tenant real el conteo por tags daba un 8 % y los estados de Terraform demostraron un 1,1 %.

Leer los estados da evidencia dura, pero incompleta: la plataforma solo ve las cuentas de estado que se le configuran.

## Decisión

- Un recurso que aparece en un estado **está gestionado**, sin heurística; se saca de los candidatos a Shadow IT.
- Un recurso que **no** aparece no se acusa por eso: puede tener su estado en otra cuenta. La regla de tags sigue siendo la que señala.
- La respuesta declara sobre cuántos estados se calculó la cifra.
- De cada estado solo se extraen `id` y `type`; el resto (que incluye secretos) se descarta sin registrarse.

## Consecuencias

- La cifra de cobertura es un piso garantizado, no una estimación.
- Aparecen los ids obsoletos: recursos gestionados por un estado que ya no existen en Azure.
- Configurar más cuentas de estado solo puede mejorar la precisión, nunca generar falsos positivos.

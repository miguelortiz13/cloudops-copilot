# Visión y propósito

## El problema

Un equipo de plataforma en Azure suele tener la información que necesita repartida en cinco portales: Resource Graph para saber qué existe, Cost Management para saber cuánto cuesta, Defender o revisiones manuales para saber qué está expuesto, los estados de Terraform para saber qué está codificado, y `kubectl` para saber qué le pasa al clúster. Cada fuente responde una pregunta aislada, y las preguntas útiles cruzan varias:

- *¿Cuál de las cuentas de almacenamiento públicas es la más cara?* (seguridad × costo)
- *¿Qué recursos se crearon a mano esta semana y quién los creó?* (inventario × historial de cambios)
- *¿Cuánto de lo que dice estar en Terraform lo está de verdad?* (tags × estados)

## Qué es CloudOps Copilot

Una capa de observación y recomendación sobre un tenant de Azure que:

1. **Consolida** inventario, costo real, postura de seguridad, cobertura de IaC y salud de Kubernetes.
2. **Cruza** esas fuentes con reglas de dominio definidas una sola vez y compartidas por el panel, los reportes y el chat.
3. **Explica** en lenguaje natural, a través de agentes de IA que reciben el mismo contexto que muestra el panel.
4. **Propone** remediaciones como código (HCL de Terraform, comandos `az`) para que una persona las revise y aplique.

## Principios

| Principio | En la práctica |
|---|---|
| **Solo lectura** | La identidad de la plataforma tiene rol `Reader`. Nada se modifica en Azure sin aprobación humana. La única excepción, el diagnóstico de AKS por Run Command, está acotada y validada (ver [security.md](security.md)). |
| **Una definición por regla** | Qué es Shadow IT, un disco huérfano o un Key Vault expuesto vive en un solo módulo (`governance.py`, `kql.py`, `pricing.py`). Si el panel y el chat dan cifras distintas, es un bug. |
| **Procedencia explícita** | Cada cifra declara si es facturación real, parcial o estimada, y sobre cuántas suscripciones se calculó. Nada se rellena con ceros. |
| **Evidencia antes que heurística** | Un recurso en un estado de Terraform *está* gestionado; un tag solo dice que alguien lo etiquetó. La plataforma distingue ambas cosas. |
| **Configurable, no a medida** | El esquema de tags, el nombre de la organización y las cuentas de estado son configuración, no código. |

## Para quién

- Equipos de plataforma, DevOps y SRE que operan Azure multi-suscripción.
- Responsables de FinOps que necesitan showback por tag sobre la factura real.
- Equipos de seguridad que quieren priorizar hallazgos por impacto.

## Qué no es

- **No es un CSPM completo.** Las reglas de seguridad cubren los hallazgos más frecuentes; no reemplazan a Defender for Cloud.
- **No remedia automáticamente.** Genera código y comandos; aplicarlos es decisión del equipo.
- **No es multi-nube (todavía).** Ver [roadmap.md](roadmap.md).

## Origen

El proyecto nació como herramienta interna de un equipo de plataforma y se reescribió como proyecto independiente: se eliminó toda configuración y dato de la organización original, se parametrizó lo específico de cada tenant y se documentó para que cualquiera pueda desplegarlo sobre su propia suscripción.

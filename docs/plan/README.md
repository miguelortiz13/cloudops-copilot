# Plan de evolución de CloudOps Copilot

Este plan describe qué le falta a la plataforma para pasar de **un panel que observa una nube** a **un sistema de operación cloud que ayuda a decidir y a actuar sobre varias nubes**, con qué arquitectura, en qué orden y con qué costo.

Está escrito para leerse por partes. Cada documento se sostiene solo y enlaza con los demás.

| # | Documento | Responde |
|---|---|---|
| 1 | [Diagnóstico](01-diagnostico.md) | Qué hay hoy, qué funciona y qué limita el crecimiento |
| 2 | [Arquitectura objetivo](02-arquitectura-objetivo.md) | Cómo debe quedar el sistema: proveedores, modelo de datos, recolectores, almacenamiento, eventos |
| 3 | [Multinube: AWS primero](03-multicloud.md) | Cómo se conecta AWS sin secretos, qué servicio cubre cada módulo, qué cuesta y qué riesgos tiene; y cómo seguiría GCP |
| 4 | [Plan por módulo](04-modulos.md) | Para cada módulo: estado, brechas, mejoras con su valor y criterios de aceptación |
| 5 | [Infraestructura de la plataforma](05-infraestructura.md) | Despliegue continuo, ambientes, base de datos, trabajos programados, observabilidad y costo |
| 6 | [Seguridad, calidad y operación](06-seguridad-calidad-operacion.md) | Autorización por rol, auditoría, pruebas, SLO, respaldo |
| 7 | [Hoja de ruta](07-hoja-de-ruta.md) | Fases, entregables, esfuerzo, costo, riesgos y métricas de éxito |

Decisiones propuestas, registradas como ADR: [0006 Abstracción de proveedores](../adr/0006-abstraccion-de-proveedores.md) · [0007 Almacén de datos y recolectores](../adr/0007-almacen-de-datos-y-recolectores.md) · [0008 FOCUS como modelo de costos](../adr/0008-focus-como-modelo-de-costos.md).

---

## Visión

> **Una sola vista operativa de toda la nube de una organización —Azure, AWS y después GCP— que responde cuánto cuesta, qué está expuesto, qué está gobernado y qué está codificado, y que convierte cada hallazgo en una acción revisable: un PR de Terraform, una alerta con dueño o un ticket con fecha.**

Hoy la plataforma cumple la primera mitad para una nube y en vivo. Le faltan tres cosas para tener valor real en una organización:

1. **Memoria.** Todo se calcula al momento y se olvida. Sin histórico no hay tendencias, ni deuda que se pague, ni evidencia para una auditoría.
2. **Ciclo de vida.** Un hallazgo se muestra, pero nadie lo asume, lo acepta como riesgo o lo cierra. Sin dueño y sin estado, el panel informa pero no cambia nada.
3. **Alcance.** Solo Azure. Casi ninguna organización mediana vive en una sola nube, y el valor de una vista unificada crece con cada proveedor.

## Principios que se mantienen

Los principios que ya rigen el código (ver [visión](../vision.md) y los ADR 0001-0005) se extienden a todo lo nuevo:

| Principio | Cómo se extiende |
|---|---|
| **Solo lectura** | En AWS, un rol IAM de solo lectura asumido por federación, sin llaves. La remediación sigue siendo código para revisar (PR), nunca una escritura directa |
| **Una definición por regla** | Las reglas pasan a un catálogo por capacidad (`exposición de almacenamiento`, `puerto de administración abierto`) con una implementación por proveedor, no a un servicio por nube |
| **Procedencia explícita** | Cada cifra declara proveedor, cuenta, fuente (factura, estimación, export), ventana y antigüedad |
| **Evidencia antes que heurística** | En AWS, CloudTrail para "quién creó qué" y los estados de Terraform en S3 para la cobertura real de IaC |
| **Costo mínimo** | Cada componente nuevo se justifica con su costo mensual. El objetivo es seguir por debajo de **USD 20/mes** en un tenant personal con dos nubes |

## Alcance, en una tabla

| Capacidad | Hoy (Azure) | Fase 2 (+AWS) | Fase 4 (+GCP) |
|---|---|---|---|
| Inventario y gobernanza de tags | En vivo (Resource Graph) | + Resource Explorer / Config | + Cloud Asset Inventory |
| Costos | Cost Management (30 días) | + CUR 2.0 en FOCUS, unificado | + Billing export a BigQuery |
| Seguridad | 7 reglas propias | + Security Hub CSPM + reglas propias | + Security Command Center |
| IaC | Estados en Azure Storage | + estados en S3 | + estados en GCS |
| Kubernetes | 1 clúster AKS | + EKS, varios clústeres | + GKE |
| Cumplimiento | ISO 27001 vía Excel | ISO 27001 + CIS sobre la base de datos | + mapeo a SOC 2 |
| Histórico y ciclo de vida | No | Sí (base de datos) | Sí |
| Alertas y acciones | Webhook manual | Alertas programadas, PR de remediación | Integraciones de tickets |

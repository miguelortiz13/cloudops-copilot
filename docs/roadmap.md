# Pendientes e integraciones futuras

> Registro de lo que falta. Las fases, sus criterios de salida y lo ya hecho están en la **[hoja de ruta](plan/07-hoja-de-ruta.md)**; el análisis completo, en el [plan de evolución](plan/README.md).

Estado al 24 de octubre de 2026: las fases 0 y 1 están cerradas, la fase 2 (AWS) está implementada con tres piezas que esperan recursos en AWS, y la fase 3 tiene 2 de sus 11 entregables hechos.

```mermaid
flowchart LR
    F0[Fase 0 · Cierre y CD<br/><b>Cerrada</b>] --> F1[Fase 1 · Fundamentos<br/><b>Cerrada</b><br/>criterios por tiempo]
    F1 --> F2[Fase 2 · AWS<br/><b>Implementada</b><br/>3 piezas bloqueadas]
    F2 --> F3[Fase 3 · Valor<br/><b>En curso</b><br/>avisos, presupuestos, reporte PDF]
    F3 --> F4[Fase 4 · Producto<br/><b>Sin empezar</b>]
    classDef hecho fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef parcial fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef curso fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    class F0,F1 hecho
    class F2 parcial
    class F3 curso
```

## Criterios que se cumplen con el tiempo

Solo hay que verificarlos en la fecha.

| Fecha | Qué verificar | Fase | Cómo |
|---|---|---|---|
| 29-oct-2026 | El job diario lleva 14 días seguidos con éxito | 1 | Administración → estado de recolectores |
| 4-nov-2026 | Llegó el primer reporte mensual (octubre) con el PDF adjunto | 3 | Canal de avisos; si falló, el paso `report` queda en error y reintenta al día siguiente |
| 5-nov-2026 | La factura de AWS de octubre coincide con el panel | 2 | Factura de AWS contra Costos → historial, mes anterior |
| 7-nov-2026 | El panel muestra 30 días de historia propia de inventario, costos y hallazgos | 1 | Costos → historial, 30 días |

## Bloqueados

No avanzan hasta que exista un recurso o se tome una decisión fuera del código.

| Pendiente | Qué lo desbloquea |
|---|---|
| StackSet de cuentas miembro de AWS | Una cuenta miembro en la organización de AWS (hoy solo existe la de gestión). La organización y sus SCP se gobiernan fuera de este proyecto |
| Leer estados de Terraform guardados en S3 | Un bucket de estados de Terraform en AWS |
| Inventario detallado y página de clústeres EKS | Un clúster EKS (los clústeres ya entran al inventario como `kubernetes.cluster`) |
| PR de remediación automático | Una GitHub App con permiso para abrir PRs en los repositorios de IaC |
| Presupuesto en el PDF descargado del panel | Pasar `MONTHLY_BUDGETS_USD` también al API con un `terraform apply` (hoy solo lo tiene el job; el PDF enviado sí lo trae) |

## Fase 3: lo que falta

Dos criterios de salida ya se cumplen (una anomalía sembrada genera aviso; el reporte mensual se envía solo). Faltan el PR de remediación y la evaluación del agente. Orden sugerido: de arriba abajo.

| Tarea | Qué entrega | Estado |
|---|---|---|
| Aviso `resource.unmanaged_created` | Avisar cuando alguien crea a mano un recurso fuera de Terraform, con quién lo creó | Sin empezar |
| Motor de eventos: correo y enrutamiento | Avisos por correo y por canal según severidad o cuenta (hoy un solo webhook) | En parte |
| PR de remediación con bloque `import` | Un hallazgo genera un PR que pasa `terraform plan` sin cambios (criterio de salida) | Bloqueado (GitHub App) |
| Pronóstico con estacionalidad | Hoy anomalías de 14 días y pronóstico lineal; falta estacionalidad semanal y mensual | En parte |
| Seguimiento del ahorro realizado | Registrar recomendaciones aplicadas y el ahorro medido después | Sin empezar |
| Cumplimiento por control con excepciones | Excepciones aprobadas por control, con vencimiento | Sin empezar |
| Agentes con herramientas, citas y evaluación | El agente usa herramientas, cita la fuente y supera el 90 % de un conjunto de preguntas verificables (criterio de salida) | Sin empezar |
| Página de Kubernetes | Vista propia de AKS y EKS con hallazgos de clúster (hoy solo en el agente) | Sin empezar |
| Bot de Teams con credencial federada | Volver a aprovisionar el bot sin secreto de cliente | Sin empezar |
| "Qué cambió" y "Mis pendientes" | Bloques del resumen con los cambios desde la última visita y lo asignado al usuario | Sin empezar |

## Integraciones futuras

Cada integración mantiene la regla de solo lectura: la plataforma propone y una persona aplica.

| Integración | Para qué | Cómo encaja | Costo estimado |
|---|---|---|---|
| Google Cloud (GCP) | Tercer proveedor: inventario, costos (export de facturación a BigQuery), hallazgos | Un `GcpProvider` más en la [capa de proveedores](adr/0006-abstraccion-de-proveedores.md), federado con Workload Identity, sin llaves | Centavos |
| Correo | Avisos para quien no usa Discord, Slack o Teams | Un canal más en el motor de eventos | USD 0 con un plan gratuito |
| Jira, Azure Boards o GitHub Issues | Convertir hallazgos en tickets con dueño y vencimiento | Acción desde la bandeja de hallazgos; el ticket enlaza de vuelta | USD 0 |
| GitHub App | PRs de remediación con bloque `import` | Credencial de la App en el job; un PR por hallazgo | USD 0 |
| Defender for Cloud y Security Hub | Sumar sus hallazgos a la bandeja sin competir con ellos | Recolector que lee sus resultados, si están activos | Lo que cueste activarlos en cada nube |
| Azure Policy y SCP | Políticas como código: estado actual y generación de la política preventiva | Lectura del estado de cumplimiento; genera código para revisar | USD 0 |
| Segundo modelo de lenguaje | Alternativa a Gemini (Azure OpenAI o Claude) | Otra implementación de la interfaz `app/llm` | Según uso |
| API pública | Que otros sistemas consulten la plataforma | Tokens de servicio con rol | USD 0 |

### Resto de la fase 4

1. Costo unitario y reparto del gasto compartido.
2. Drift de recursos gestionados por Terraform.
3. Exposición por rutas (combinaciones de hallazgos).
4. Agente ligero dentro de clústeres privados.
5. Alcance por equipo (multiinquilino interno).
6. Ambiente `prod` separado con aprobación manual (hoy solo existe `dev`).
7. Empaquetado como Helm chart para AKS.

**Fuera de alcance a propósito:** remediación automática, reemplazar un CSPM o un SIEM y orquestar despliegues de aplicaciones.

## Deuda técnica

- [ ] Revisar por qué el panel cuenta 8 recursos de AWS en Terraform cuando los estados tienen 9 ARNs.
- [ ] Revisar por qué solo 3 de 9 creaciones de CloudTrail se asocian a un recurso.
- [ ] Crear `docs/runbooks/` con los runbooks del [plan](plan/06-seguridad-calidad-operacion.md#runbooks).
- [ ] Decidir si se despliegan Key Vault (clave de Gemini como referencia de secreto) y Application Insights con tope diario.
- [ ] Convertir moneda en presupuestos y reporte (hoy se suma todo como USD; marcado `shortcut` en el código).
- [ ] Retirar los `from x import *` de los routers.
- [ ] Propagar `forceRefresh` en el camino KQL de `/api/inventory/resources` (hoy se ignora; marcado con `TODO`).
- [ ] Retirar endpoints heredados (`/api/stats`, `/api/resources`, `/api/subscriptions`, `/api/recommendations*`) cuando el panel deje de usarlos.
- [ ] Logging estructurado (JSON) en lugar de `print`, con correlación por petición.
- [ ] Cobertura de pruebas medida en la CI.
- [ ] Hacer configurables las claves de custodio y de evidencia IaC (`governance.py`) igual que las tags obligatorias.
- [ ] Respuestas en streaming en el chat.
- [ ] Generar `frontend/src/lib/types.ts` desde el OpenAPI.
- [ ] Revisión de accesibilidad con lector de pantalla y navegación completa por teclado.
- [ ] Borrar las ramas `feat/*` ya mergeadas en GitHub.

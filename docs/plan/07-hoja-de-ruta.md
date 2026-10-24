# 7. Hoja de ruta

Cinco fases. Cada una termina con algo usable y con criterios de salida verificables; ninguna empieza sin que la anterior cumpla los suyos. Las duraciones suponen una persona con dedicación parcial (unas 15 h por semana).

```mermaid
gantt
    title CloudOps Copilot · hoja de ruta
    dateFormat  YYYY-MM-DD
    axisFormat  %b
    section Fase 0
    Cierre y despliegue continuo        :f0, 2026-10-12, 14d
    section Fase 1
    Fundamentos (datos, proveedores, ciclo de vida) :f1, after f0, 42d
    section Fase 2
    AWS                                  :f2, after f1, 42d
    section Fase 3
    Valor (alertas, PRs, cumplimiento, agentes) :f3, after f2, 42d
    section Fase 4
    Producto (GCP, políticas, costo unitario) :f4, after f3, 60d
```

---

## Fase 0 · Cierre y despliegue continuo (2 semanas)

**Objetivo:** dejar lo actual cerrado, seguro y desplegándose solo.

| Entregable | Detalle | Estado |
|---|---|---|
| Merge de PRs #1, #2 y el de este plan | `main` refleja lo desplegado | Hecho (#1, #2, #3) |
| Verificación del inicio de sesión en el panel | Primer uso real de Entra ID en el navegador | Hecho |
| Remediación de los hallazgos abiertos del laboratorio | Vía Terraform del proyecto correspondiente, para que la plataforma los vea cerrarse | Fuera de alcance: los hallazgos son de otros proyectos y este plan solo cambia CloudOps Copilot |
| Imagen en GitHub Container Registry | Elimina la dependencia del ACR de otro proyecto | Hecho (v2.4.0) |
| Despliegue continuo con GitHub Actions + OIDC a `dev` | Build y publicación de la imagen, despliegue del API y del panel al hacer merge, smoke test | Hecho (v2.4.0). La infraestructura sigue aplicándose a mano con Terraform; el plan comentado en PRs pasa a la fase 1 |
| Escaneo de dependencias e imagen en CI | Dependabot, `pip-audit`, `npm audit`, Trivy | Hecho (v2.4.0) |
| Cabeceras de seguridad en el panel | `staticwebapp.config.json` | Hecho (v2.4.0) |

**Criterios de salida:** un merge a `main` despliega solo y pasa el smoke test; ningún secreto en GitHub; el panel abre con inicio de sesión.

**Costo incremental:** USD 0.

---

## Fase 1 · Fundamentos (6 semanas)

**Objetivo:** que la plataforma tenga memoria, un modelo independiente de la nube y procesos fuera del API. Es la fase menos vistosa y la que habilita todo lo demás.

| Entregable | Módulo | Detalle | Estado |
|---|---|---|---|
| Base de datos (Azure SQL gratuita) con SQLAlchemy y Alembic | Plataforma | Esquema del [modelo canónico](02-arquitectura-objetivo.md#modelo-canónico) | Hecho |
| Capa de proveedores con `AzureProvider` | Plataforma | Extraer de `services/` y `agents/azure_agent.py`; pruebas de contrato con fixtures | Hecho para los recolectores: `AzureProvider` (inventario, costos, seguridad, IaC, actividad) con contrato sobre respuestas grabadas; el chat y las vistas en vivo siguen sobre los servicios |
| Job diario de recolección | Plataforma | inventory, costs, findings, iac_states, activity, kpis | Hecho: inventario (con estado IaC y creador como campos del recurso), costos, hallazgos y KPIs |
| Inyección de dependencias con `Depends` | API | Reemplaza `get_services()[n]` | Hecho |
| Ciclo de vida de hallazgos | Seguridad / Hallazgos | Abierto, asumido, resuelto, aceptado con vencimiento | Hecho: automático en el recolector y gestión en el panel (asumir, aceptar con vencimiento y justificación, reabrir) |
| Catálogo de reglas con mapeo CIS / ISO | Seguridad / Cumplimiento | Las 7 reglas actuales, migradas | Hecho: mapeo a CIS Azure 2.0.0 (8 controles) e ISO 27001:2022 (10), con evidencia directa o parcial y estado por control en el panel |
| Costos desde la base, selector de periodo, comparación mes a mes | Costos | Export FOCUS de Azure Cost Management | Hecho con la API de consultas (un año de historia); el export FOCUS queda para costo amortizado |
| Clasificación ISO en la base (sin Excel) | Cumplimiento | | Hecho: paso `classification` del recolector, corrección manual auditada y exportación CSV |
| Roles (lector, operador, administrador) y auditoría | Seguridad | App roles de Entra ID | Hecho, con grupos de seguridad por rol |
| Interfaz de LLM y migración a `google-genai` | Agentes | Con límite de uso por usuario | Hecho |
| Administración: cuentas conectadas y estado de recolectores | Administración | Primera versión | Hecho: actividad de usuarios, cuentas conectadas con permisos efectivos y capacidades por proveedor, y estado de base y recolectores. La reejecución manual de recolectores queda para la fase 3 |
| Pruebas de frontend (Vitest) y E2E con Playwright | Calidad | Capturas anonimizadas como regresión visual | Hecho: 43 pruebas de Vitest, 38 E2E y 12 capturas con datos ficticios, en la CI |


**Criterios de salida:**
- El panel muestra 30 días de historia propia de inventario, costos y hallazgos.
- Un hallazgo corregido se marca resuelto solo.
- El job diario termina con éxito 14 días seguidos.
- El consumo de la base de datos queda medido y dentro del cupo gratuito, o con la decisión tomada. **Cumplido:** 11 % del cupo a mitad de mes, proyección del 25 % ([detalle](05-infraestructura.md#consumo-medido-octubre-de-2026)).
- `azure_agent.py` deja de existir como pieza monolítica. **Cumplido:** de 1.346 a 399 líneas; contexto, prompts, consultas en vivo y motor de reglas en módulos propios.

**Costo incremental:** USD 0-2/mes.

---

## Fase 2 · AWS (6 semanas)

**Objetivo:** paridad de los módulos principales con AWS en las mismas vistas.

| Paso | Entregable | Puerta |
|---|---|---|
| 1 | **Prueba de concepto de federación**: la identidad administrada asume un rol de AWS por OIDC | **Cumplido** (14-oct-2026): asumió el rol de lectura desde el job, sin llaves; registrado en CloudTrail |
| 2 | Módulo `infra/modules/aws-onboarding` (OIDC, rol hub, StackSet, CUR 2.0, Resource Explorer) | **Cumplido en parte** (14-oct-2026): aplicado en la organización de laboratorio con OIDC, rol hub, Resource Explorer agregador con vista propia y export FOCUS 1.2 a S3. Falta el StackSet de cuentas miembro: necesita una cuenta miembro de laboratorio |
| 3 | `AwsProvider.inventory` con tipos canónicos | **Cumplido** (15-oct-2026; verificado en el job: 72 recursos de AWS): `app/providers/aws` lee la vista de Resource Explorer con credenciales federadas y pasa la batería de contrato. El job corre `inventory_aws` en su propia ejecución; Administración y la clasificación ISO muestran las dos nubes |
| 4 | `AwsProvider.costs` sobre CUR 2.0 FOCUS + Athena | **Implementado** (15-oct-2026; el export entrega desde el 16-oct y `costs_aws` corre a diario): Athena con proyección de particiones y tope por consulta; paso `costs_aws` en el job. Falta comparar un mes cerrado con la factura: la primera entrega del export todavía no llegó |
| 5 | Reglas AWS del catálogo y recursos sin uso | **Implementado** (18-oct-2026): 5 reglas de seguridad (CIS AWS 3.0.0 e ISO) y 2 de recursos sin uso en la misma bandeja (`findings_aws`); el inventario deja fuera los recursos que AWS crea solo |
| 6 | Estados de Terraform en S3 con resolución de ARN | **Cumplido en parte** (19-oct-2026): los estados que ya lee la plataforma reconocen los recursos de AWS por su atributo `arn` (9 recursos del laboratorio en IaC). Leer estados guardados en S3 queda para cuando exista un bucket de estados |
| 7 | Actividad desde CloudTrail | **Implementado** (18-oct-2026): quién creó cada recurso en los últimos 90 días (historial de eventos, sin trail); persona vs. automatización (Terraform, servicios de AWS) |
| 8 | Filtros por proveedor y cuenta en todo el panel | **Implementado** (18-oct-2026): selector único por nube y cuenta; hallazgos, activos y reporte se filtran en el navegador, el historial de costos en el servidor (por nube completa, precalculado); las vistas en vivo de Azure avisan si el filtro no incluye Azure |
| 9 | Inventario de clústeres EKS | **Pendiente sin bloqueo**: los clústeres EKS ya entran al inventario como `kubernetes.cluster`. El panel no tiene página de Kubernetes (vive en el agente de IA) y el laboratorio no tiene clústeres: se hace cuando exista uno |

**Criterios de salida:** una cuenta de AWS de laboratorio aparece en todas las vistas con datos reales; ninguna llave de AWS guardada; la factura de AWS del mes coincide con el panel.

**Costo incremental:** USD 1-3/mes (S3 y Athena del export en el laboratorio).

---

## Fase 3 · Valor (6 semanas)

**Objetivo:** que la plataforma avise, actúe y demuestre su valor.

| Entregable | Módulo |
|---|---|
| Motor de eventos y notificaciones (Teams, Slack, correo) con deduplicación | Integraciones · **En curso** (20-oct-2026): paso `notify` del job con `finding.opened` (alta y crítica), `collector.failed`, `cost.anomaly` (media de 14 días + 3σ o el doble, desde 0,50 USD) y `budget.threshold` (80 %, 100 % y pronóstico) a un webhook de Discord, Slack o Teams, sin repetir avisos. Faltan correo, enrutamiento por severidad o cuenta y `resource.unmanaged_created` |
| PR de remediación con bloque `import` (GitHub App) | IaC / Hallazgos |
| Anomalías estadísticas y pronóstico con estacionalidad | Costos · **En parte** (22-oct-2026): anomalía diaria por cuenta (14 días, 3σ o 2×) y pronóstico lineal del mes; falta la estacionalidad |
| Seguimiento del ahorro realizado | Costos |
| Presupuestos con alertas | Costos · **Hecho** (22-oct-2026): presupuesto mensual por nube (`monthly_budgets_usd`) con aviso al 80 %, 100 % y por pronóstico |
| Vista de cumplimiento por control con excepciones | Cumplimiento |
| Agentes con herramientas, citas y conjunto de evaluación | Agentes |
| Página de Kubernetes y hallazgos de clúster | Kubernetes · **En curso** (24-oct-2026): agente de solo lectura dentro del clúster (AKS, EKS o fuera de la nube) y página con salud, nodos, cargas e incidencias; avisos casi en vivo, logs de los pods con problemas y chat sobre la foto ([plan del módulo](08-kubernetes.md)); faltan historia, hallazgos de clúster y flota |
| Reporte ejecutivo mensual en PDF | Reportes · **Hecho** (23-oct-2026): PDF de costos contra presupuesto, hallazgos, inventario y salud del job, descargable en Reportes; el paso `report` del job lo envía solo el día 4 al webhook de avisos (adjunto en Discord, enlace en Slack y Teams) |
| Bot de Teams con credencial federada | Integraciones |
| Bloque "Qué cambió" y "Mis pendientes" en el resumen | Resumen |

**Criterios de salida:** una anomalía sembrada genera alerta; un hallazgo genera un PR que pasa `terraform plan` sin cambios; el reporte mensual se envía solo; el agente supera el 90 % del conjunto de evaluación.

**Costo incremental:** USD 0-5/mes (costo del modelo de IA según uso).

---

## Fase 4 · Producto (continua)

Se prioriza según el uso real. Candidatos, en orden sugerido:

1. **GCP** como tercer proveedor.
2. **Políticas como código**: estado de Azure Policy, SCP y políticas de tags; generación de la política preventiva.
3. **Costo unitario** y reparto del gasto compartido.
4. **Drift** de recursos gestionados por Terraform.
5. Integración con tickets (Jira, Azure Boards, GitHub Issues).
6. Exposición por rutas (combinaciones de hallazgos).
7. Agente ligero dentro de clústeres privados.
8. Alcance por equipo (multiinquilino interno).
9. API pública con tokens de servicio.

---

## Riesgos del plan

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| La federación Entra → AWS no funciona con el token de la identidad administrada | Media | Alto | Es el primer paso de la fase 2 y una puerta explícita |
| El cupo gratuito de Azure SQL no alcanza | Media | Bajo | Medido en la fase 1; salida a PostgreSQL B1ms sin cambiar código |
| La refactorización a proveedores rompe reglas existentes | Media | Alto | Pruebas de contrato + prueba de fidelidad KQL antes y después |
| Alcance excesivo para una persona | Alta | Medio | Fases con criterios de salida; la fase 4 se prioriza por uso |
| Los límites de tasa de las APIs de costos | Alta | Medio | Exports en lugar de APIs de consulta como fuente principal |
| Exponer datos reales en el repositorio público | Media | Alto | Capturas siempre anonimizadas; fixtures de pruebas sintéticos; gitleaks en CI |

## Cómo medir que la plataforma tiene valor

| Métrica | Fuente | Objetivo a 6 meses |
|---|---|---|
| Ahorro realizado acumulado | Seguimiento de ahorro | Mayor que el costo de la plataforma × 10 |
| MTTR de hallazgos críticos | Ciclo de vida | < 7 días |
| Cobertura real de IaC | Estados de Terraform | +20 puntos frente al inicio |
| Cumplimiento de tags obligatorias | Inventario | > 95 % |
| Gasto sin atribuir (sin tag de showback) | Costos | < 10 % |
| Hallazgos aceptados con vencimiento vigente | Ciclo de vida | 100 % (ninguno aceptado sin fecha) |

## Lo que queda fuera a propósito

- **Remediación automática.** La plataforma propone código; las personas lo aprueban. Es el [ADR 0001](../adr/0001-identidad-de-solo-lectura.md) y no cambia.
- **Reemplazar un CSPM o un SIEM.** Se integra con Defender, Security Hub o SCC en lugar de competir con ellos.
- **Gestión de despliegues.** No orquesta pipelines de aplicación; observa lo que dejan.

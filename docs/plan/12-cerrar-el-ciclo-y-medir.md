# 12. Fase 7 · Cerrar el ciclo y medir el valor

La plataforma ya detecta, diagnostica y prioriza (fases 1 a 5 del [plan 10](10-reestructuracion-por-dominios.md) y la [plataforma de IA](11-plataforma-ia.md)). Lo que todavía no hace es **aprender de lo que pasó, demostrar con números que mejora la operación y operar con objetivos de servicio**. Esta fase cierra ese ciclo.

Escrito el 10-nov-2026, a partir de la revisión de casos de uso de DevOps y SRE. Resumen comentable en Claude Docs ("CloudOps Copilot · Plan de reestructuración por dominios", sección *Fase 7*).

## Por qué

| Lo que vimos en producción (9-nov) | Consecuencia |
|---|---|
| Los incidentes se cierran solos cuando la alerta se resuelve y nadie marca el diagnóstico; la base de conocimiento tiene 0 incidentes reales | No sabemos si el diagnóstico acierta fuera del eval y el agente no recuerda nada |
| Las alertas ruidosas se cierran como ruido una y otra vez | El ruido vuelve cada semana; nadie lo convierte en silencio o en un ajuste de la regla |
| El post-mortem termina en **Acciones** que nadie sigue | Se repiten los mismos incidentes |
| Las métricas existen sueltas (incidentes, hallazgos, ahorro, evals) | No se puede responder "¿mejoró el MTTR este mes?" |
| Se reacciona a alertas, no a objetivos | Sin SLO ni presupuesto de error no se prioriza confiabilidad contra velocidad |

## Mejoras, en orden

### 7.1 Cerrar el ciclo del incidente

- **Marcar el diagnóstico**: un incidente resuelto con diagnóstico y sin marca aparece en *Mis pendientes* durante 14 días (para su responsable, o para todos si no tiene).
- **Ruido a silencio**: una alerta cerrada como ruido o falso positivo dos o más veces en 14 días, sin silencio vigente, aparece en *Mis pendientes* como "alerta ruidosa" con el enlace al último incidente, donde está *Silenciar similares…*.
- **Acciones del post-mortem**: las viñetas de **Acciones** del post-mortem se convierten en tareas del incidente (texto, responsable, hecha), con su línea de tiempo; las abiertas aparecen en *Mis pendientes* de su responsable.

**Aceptación**: la proporción de incidentes resueltos con diagnóstico marcado sube semana a semana; la base de conocimiento empieza a tener incidentes reales.

### 7.2 Tablero de valor

En *Inicio*, con tendencia semanal de las últimas 8 semanas:

| Indicador | Fuente |
|---|---|
| Tiempo hasta reconocer y hasta resolver (mediana) | Incidentes y su línea de tiempo |
| % de incidentes que eran ruido | Motivo de cierre |
| % de diagnósticos correctos (marcados) y cobertura de marcas | Marcas de las personas |
| Hallazgos críticos y altos: abiertos, cerrados y días para cerrar | Hallazgos y sus eventos |
| Ahorro realizado (verificado) | *Costos → Ahorro* |
| Evals de la IA | Corrida semanal |

**Aceptación**: el reporte mensual y el resumen semanal citan estos indicadores con su tendencia.

*Construido*: el tiempo hasta reconocer es hasta la primera acción de una persona en el incidente (estado, responsable, nota o acción); la semana en curso se muestra pero no se compara; el resumen semanal recibe `tendencia` (última semana cerrada y la anterior) y el bloque de incidentes del reporte mensual suma la mediana para reconocer.

### 7.3 SLOs con presupuesto de error

- Un SLO por servicio: disponibilidad o latencia, con la fuente (chequeo HTTP de la plataforma o una consulta a Prometheus que envía el agente del clúster), el objetivo (por ejemplo 99,5 % en 28 días) y su presupuesto de error.
- Quemar el presupuesto más rápido de lo debido abre un incidente (alerta de *burn rate*); el incidente y el reporte citan el SLO afectado.

**Aceptación**: al menos un servicio del laboratorio con SLO; un incidente sembrado consume presupuesto y se ve en el tablero.

### Después

| Mejora | Valor |
|---|---|
| Asignación por reglas (tag `Owner`, namespace, clúster) | *Mis pendientes* sin "sin responsable" en un equipo |
| Remediación por PR (MCP cliente de GitHub, bloque `import` o fix de Terraform) con aprobación humana | Menos tiempo entre hallazgo y corrección |
| Cambios de la nube desde Activity Log y CloudTrail como fuente del diagnóstico | Incidentes de Azure y AWS con su causa, no solo los de Kubernetes |

## Avance

| Entrega | Estado |
|---|---|
| 7.1 Cerrar el ciclo del incidente: marcas, alertas ruidosas y acciones del post-mortem en *Mis pendientes* ([incidentes](../modules/incidents.md#cerrar-el-ciclo)) | Hecho |
| 7.2 Tablero de valor en *Inicio* (`GET /api/inicio/valor`): última semana cerrada contra la anterior y tendencia; el resumen semanal y el reporte mensual citan la tendencia y el tiempo hasta reconocer | Hecho |
| 7.3 SLOs con presupuesto de error sobre los chequeos HTTP, alerta de quema en dos ventanas y *Operación → SLOs* ([incidentes](../modules/incidents.md#slos-y-presupuesto-de-error)) | Hecho |

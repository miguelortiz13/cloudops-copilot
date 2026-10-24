# Requerimientos

Qué debe hacer la plataforma y bajo qué condiciones. El estado de cada requerimiento sigue la [hoja de ruta](plan/07-hoja-de-ruta.md); lo que falta está en [pendientes](roadmap.md).

## Funcionales

| ID | Requerimiento | Estado |
|---|---|---|
| RF-01 | Inventario de Azure (suscripciones y management groups) y de AWS (Resource Explorer) en un modelo canónico único | Hecho |
| RF-02 | Costos diarios reales: Azure por la API de consultas de Cost Management, AWS por el export FOCUS 1.2 consultado con Athena; un año de historia | Hecho (AWS sin comparar todavía con una factura cerrada) |
| RF-03 | Comparación por periodo (7, 30 y 90 días, mes en curso, mes anterior), por nube y por cuenta | Hecho |
| RF-04 | Hallazgos de seguridad con un catálogo de reglas mapeado a CIS Azure 2.0.0, CIS AWS 3.0.0 e ISO 27001:2022 | Hecho |
| RF-05 | Ciclo de vida de hallazgos: abierto, asumido, aceptado con vencimiento, resuelto automático, reabierto | Hecho |
| RF-06 | Cobertura real de Terraform leída de los estados (Azure por id, AWS por ARN) y generación de HCL con bloques `import {}` | Hecho |
| RF-07 | Quién creó cada recurso (Activity Log de Azure, CloudTrail de AWS) | Hecho |
| RF-08 | Clasificación ISO de activos con corrección manual auditada y exportación CSV | Hecho |
| RF-09 | Roles lector, operador y administrador, con auditoría de cada escritura | Hecho |
| RF-10 | Chat con agentes de IA que usan el mismo contexto y las mismas reglas que el panel; motor de reglas local si no hay modelo | Hecho |
| RF-11 | Avisos automáticos a Discord, Slack o Teams sin repetirse | Hecho |
| RF-12 | Presupuesto mensual por nube con aviso al 80 %, al 100 % y por pronóstico | Hecho |
| RF-13 | Reporte ejecutivo mensual en PDF, descargable desde el panel y enviado solo | Hecho |
| RF-14 | Diagnóstico de AKS con un agente SRE (`kubectl` validado vía Run Command) | Hecho (sin página propia en el panel) |

## No funcionales

| Categoría | Requerimiento |
|---|---|
| Seguridad | La identidad de la plataforma solo lee: rol Reader en Azure y un rol de lectura en AWS asumido por federación OIDC. Ninguna llave de AWS guardada ([ADR 0001](adr/0001-identidad-de-solo-lectura.md)) |
| Seguridad | El API exige un token de Entra ID en el despliegue; solo los usuarios asignados obtienen token |
| Seguridad | El webhook de avisos es una credencial: va como secreto de Container Apps y nunca aparece en logs ni errores (solo el host) |
| Privacidad | El repositorio es público: nunca IDs reales de cuentas o suscripciones, ARNs, `*.tfvars`, `backend.hcl`, estados ni capturas sin anonimizar. gitleaks corre en la CI |
| Costo | La plataforma cuesta menos de USD 5 al mes; la base de datos queda dentro del cupo gratuito ([consumo medido](plan/05-infraestructura.md#consumo-medido-octubre-de-2026)) |
| Disponibilidad | API disponible el 99 % del mes; el job diario termina bien en al menos el 95 % de las ejecuciones |
| Frescura | Inventario e historia con menos de 26 h; costos con menos de 30 h (las nubes consolidan con retraso) |
| Rendimiento | Las vistas por defecto salen de una caché precalculada; p95 por debajo de 1,5 s sin contar el arranque en frío |
| Recuperación | RPO de 24 h y RTO de 2 h; los datos de las nubes se reconstruyen reejecutando el job |
| Calidad | Cada PR pasa ruff, pytest, eslint, Vitest, Playwright con regresión visual, Trivy, `pip-audit`, `npm audit`, gitleaks y `terraform validate` |

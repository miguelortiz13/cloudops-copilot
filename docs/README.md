# Documentación de CloudOps Copilot

> **[Plan de evolución](plan/README.md)**: diagnóstico, arquitectura objetivo, multinube, mejoras por módulo, infraestructura y hoja de ruta por fases. Lo que falta está en **[pendientes e integraciones futuras](roadmap.md)**.

## Producto

| Documento | Para qué |
|---|---|
| [Visión y propósito](vision.md) | Qué problema resuelve, para quién y qué no pretende hacer |
| [Requerimientos](requirements.md) | Requerimientos funcionales y no funcionales, con su estado |

## Diseño del sistema

| Documento | Para qué |
|---|---|
| [Arquitectura](architecture.md) | Componentes, capas del backend y servicios |
| [Flujos](flows.md) | Job diario, avisos, reporte mensual, inicio de sesión y despliegue, con diagramas |
| [Modelo de datos](data-model.md) | Tablas del modelo canónico y lecturas sin abrir la base |
| [Decisiones de arquitectura (ADR)](adr/README.md) | Por qué el sistema es como es |

## Para empezar

| Documento | Para qué |
|---|---|
| [Primeros pasos](getting-started.md) | Levantar la plataforma en local, con o sin Docker |
| [Configuración](configuration.md) | Referencia de todas las variables de entorno |
| [Guía de desarrollo](development.md) | Estructura, pruebas, estilo y CI |

## Operación

| Documento | Para qué |
|---|---|
| [Despliegue en Azure](deployment.md) | Permisos, estado de Terraform, despliegue y destrucción |
| [Operación](operations.md) | Recursos desplegados, costo, tareas del día a día y cambios de infraestructura |
| [Seguridad](security.md) | Modelo de amenazas, autenticación, roles y controles |
| [API](api.md) | Catálogo de endpoints |

## Módulos

- [Inventario y gobernanza](modules/inventory-governance.md)
- [FinOps](modules/finops.md)
- [SecOps](modules/secops.md)
- [Cumplimiento](modules/compliance.md)
- [IaC y Terraform](modules/iac.md)
- [Avisos y reportes](modules/notifications-reports.md)
- [Agentes de IA](modules/ai-agents.md)
- [Kubernetes SRE](modules/kubernetes-sre.md)
- [Pipeline de inventario](modules/inventory-pipeline.md)

## Gobernanza de referencia

- [Política de tags](governance/tagging-policy.md)
- [Convención de nombres](governance/naming-convention.md)

## Integraciones

- [Microsoft Teams](integrations/teams.md)
- Discord y Slack: ver [avisos y reportes](modules/notifications-reports.md#destino-según-el-webhook)

## Seguimiento

- [Hoja de ruta por fases](plan/07-hoja-de-ruta.md)
- [Pendientes e integraciones futuras](roadmap.md)
- [Changelog](../CHANGELOG.md)

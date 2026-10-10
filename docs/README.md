# Documentación de CloudOps Copilot

> **[Plan de evolución](plan/README.md)**: diagnóstico, arquitectura objetivo, multinube (AWS primero), mejoras por módulo, infraestructura y hoja de ruta por fases.

## Para empezar

| Documento | Para qué |
|---|---|
| [Visión y propósito](vision.md) | Qué problema resuelve, para quién y qué no pretende hacer |
| [Primeros pasos](getting-started.md) | Levantar la plataforma en local, con o sin Docker |
| [Configuración](configuration.md) | Referencia de todas las variables de entorno |
| [Arquitectura](architecture.md) | Componentes, flujo de datos y decisiones de diseño |

## Operación

| Documento | Para qué |
|---|---|
| [Despliegue en Azure](deployment.md) | Permisos, estado de Terraform, despliegue y destrucción |
| [Seguridad](security.md) | Modelo de amenazas, autenticación y controles |
| [API](api.md) | Catálogo de endpoints |

## Módulos

- [Inventario y gobernanza](modules/inventory-governance.md)
- [FinOps](modules/finops.md)
- [SecOps](modules/secops.md)
- [Cumplimiento](modules/compliance.md)
- [IaC y Terraform](modules/iac.md)
- [Agentes de IA](modules/ai-agents.md)
- [Kubernetes SRE](modules/kubernetes-sre.md)
- [Pipeline de inventario](modules/inventory-pipeline.md)

## Gobernanza de referencia

- [Política de tags](governance/tagging-policy.md)
- [Convención de nombres](governance/naming-convention.md)

## Integraciones

- [Microsoft Teams](integrations/teams.md)

## Desarrollo

- [Guía de desarrollo](development.md): estructura, pruebas, estilo y CI
- [Decisiones de arquitectura (ADR)](adr/README.md)
- [Roadmap](roadmap.md)
- [Changelog](../CHANGELOG.md)

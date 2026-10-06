# Política de seguridad

## Reportar una vulnerabilidad

No abras un issue público. Usa [GitHub Security Advisories](https://github.com/miguelortiz13/cloudops-copilot/security/advisories/new) para reportarla de forma privada, con:

- descripción y componente afectado;
- pasos para reproducirla;
- impacto estimado.

Recibirás respuesta en un plazo de 7 días.

## Alcance

Especialmente relevantes: evasión de la autenticación del API o del webhook de Teams, inyección de comandos en el agente de Kubernetes, fuga de datos de los estados de Terraform y exposición de credenciales.

El modelo de amenazas y los controles están en [docs/security.md](docs/security.md).

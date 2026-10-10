# Seguridad

## Modelo de amenazas

La plataforma concentra una vista completa del tenant: inventario, costos, hallazgos de seguridad e identidades que crearon recursos. Quien acceda al API obtiene un mapa de ataque. Los controles se diseñaron alrededor de tres preguntas.

| Activo | Amenaza | Control |
|---|---|---|
| Inventario y hallazgos | Lectura por cualquiera que conozca la URL | Entra ID en el API, CORS restringido, webhook de Teams autenticado |
| Tenant observado | Modificación accidental o maliciosa a través de la plataforma | Identidad con rol `Reader`; ningún endpoint escribe en Azure |
| Clúster AKS | Inyección de comandos vía el agente SRE | Validación RFC 1123 y lista negra de metacaracteres antes de Run Command |
| Estados de Terraform | Fuga de secretos contenidos en el estado | Solo se extraen `id` y `type`; el resto se descarta sin registrarse |
| Credenciales | Fuga en el repositorio | `.env`, `*.tfvars`, `backend.hcl` y estados ignorados por git; gitleaks en CI |

## Autenticación del API

Con `AUTH_ENABLED=true` el middleware ([`services/auth.py`](../backend/app/services/auth.py)) exige un bearer token de Microsoft Entra ID y valida firma (JWKS del tenant, con renovación ante un `kid` desconocido), emisor, audiencia (`AZURE_AD_API_CLIENT_ID`) y expiración.

Rutas siempre públicas:

| Ruta | Motivo |
|---|---|
| `/` | Estado básico del servicio |
| `/api/inventory/health` | Health check; no expone secretos |
| `/api/teams/webhook` | Lo invoca Bot Framework, con su propia autenticación |

El panel obtiene el token con MSAL ([`frontend/src/auth.ts`](../frontend/src/auth.ts)) y lo adjunta a cada llamada mediante `apiFetch`. MSAL se carga de forma dinámica y solo cuando la autenticación está configurada.

> En local `AUTH_ENABLED=false` facilita el desarrollo. **El despliegue de Terraform siempre lo activa**, y además restringe el inicio de sesión a los usuarios asignados en las dos app registrations (`app_role_assignment_required`): una cuenta del tenant sin asignación no obtiene token ni en el panel ni desde la CLI.

### Registro de aplicaciones en Entra ID

1. **API**: App Registration con un scope expuesto `access_as_user`. Su client id es `AZURE_AD_API_CLIENT_ID`.
2. **Panel**: App Registration tipo SPA con redirect URI a la URL de la Static Web App y permiso delegado sobre el scope del API. Su client id es `VITE_AZURE_AD_CLIENT_ID`; `VITE_API_SCOPE=api://<client id del API>/access_as_user`.

## Autorización por rol

Autenticarse solo prueba quién eres. Lo que puedes hacer depende del **grupo de seguridad de Entra ID** al que perteneces. Terraform crea un grupo por rol y define sus miembros con la variable `role_members`:

| Grupo de Entra ID | Rol |
|---|---|
| `CloudOps Copilot <ambiente> - Administradores` | Administrador |
| `CloudOps Copilot <ambiente> - Operadores` | Operador |
| `CloudOps Copilot <ambiente> - Lectores` | Lector |

El token del API lleva los grupos del usuario (claim `groups`, con `groupMembershipClaims = SecurityGroup`). [`app/core/authz.py`](../backend/app/core/authz.py) los traduce con los object ids que recibe en `AUTHZ_GROUP_ADMIN`, `AUTHZ_GROUP_OPERATOR` y `AUTHZ_GROUP_READER`. También cuentan los app roles `CloudOps.*` del token, y gana el rol mayor.

**Por qué grupos y asignación por usuario a la vez.** El tenant está en Entra ID Free, que no permite asignar grupos a una aplicación (eso requiere P1 o P2). Por eso Terraform asigna al API (con el app role mínimo, Reader) y al panel a cada miembro de los grupos: la asignación abre la puerta y el grupo decide el rol. Si alguien se agrega a un grupo solo desde el portal, obtiene el rol pero no el acceso; hay que agregarlo en `role_members`. Con P1 se podría asignar el grupo directamente y quitar esa duplicación.

| Rol | Grupo | Puede |
|---|---|---|
| Lector | Lectores | Todo lo que lee: inventario, costos, seguridad, IaC, cumplimiento y chat |
| Operador | Operadores | Además gestionar hallazgos (asumir, aceptar riesgos), clasificar activos a mano, ejecutar la sincronización, usar el agente de Kubernetes (ejecuta `kubectl` vía AKS Run Command) y enviar alertas de prueba a Teams |
| Administrador | Administradores | Además ver el estado de la base y la auditoría, y reiniciar el cliente de Kubernetes |

- Un usuario asignado sin grupo ni app role es **lector**: tener acceso nunca implica poder escribir. Un grupo que no esté configurado en `AUTHZ_GROUP_*` no da permisos.
- El backend decide (403). El panel solo oculta o desactiva lo que el rol no permite, para no ofrecer acciones que fallarían.
- Con `AUTH_ENABLED=false` (desarrollo local) todo el mundo es administrador, y el panel lo muestra como "sin autenticación".

## Auditoría

Toda acción que cambia algo o actúa sobre la nube queda registrada: cambios de estado de hallazgos, clasificaciones manuales de activos, sincronización, comandos del agente de Kubernetes, alertas de prueba a Teams y reinicio de clientes. Se guarda quién la hizo (UPN y object id del token), con qué rol, sobre qué objeto, con qué resultado y con qué detalle.

- Va siempre al log como una línea JSON (`[audit] {...}`) y, si hay base, a la tabla `audit_log`. Los administradores la ven en **Administración → Actividad de usuarios** (`GET /api/admin/audit`).
- La URL de un webhook de Teams es una credencial: solo se audita su host.
- Un fallo al auditar no bloquea la acción; queda en el log.
- Los intentos denegados (403) quedan en el log, no en la base, para que nadie pueda despertarla a voluntad con peticiones prohibidas.

## Webhook de Teams

`/api/teams/webhook` valida en cada actividad el JWT que firma Bot Framework ([`services/bot_auth.py`](../backend/app/services/bot_auth.py)):

- firma contra las llaves públicas del emisor (`https://api.botframework.com` y los emisores del tenant, porque el bot es `SingleTenant`);
- audiencia igual a `MICROSOFT_APP_ID`;
- expiración;
- coincidencia del `serviceUrl` de la actividad con el del token.

Sin esta validación el endpoint entregaría el inventario a cualquiera que conociera la URL. Se controla con `BOT_AUTH_ENABLED` (activo por defecto).

## CORS

Solo los orígenes de `ALLOWED_ORIGINS` (o `FRONTEND_URL` y los puertos de desarrollo) pueden llamar al API. Nunca se usa `*` junto con `allow_credentials`. El middleware CORS se registra después del de autenticación para que las respuestas `401` también lleven cabeceras CORS y el navegador pueda leer el motivo.

## Agente SRE de Kubernetes

Es el único camino de la plataforma que ejecuta algo dentro de un recurso del cliente: `kubectl` a través de AKS Run Command.

- Los nombres de pod, namespace y contenedor que llegan del cliente deben cumplir **RFC 1123**.
- Ningún comando puede contener metacaracteres de shell (`; | & $` comillas, redirecciones, paréntesis, comodines, saltos de línea).
- La validación se repite como última barrera justo antes de ejecutar.
- Los comandos los construye el servicio, nunca el cliente, y son todos de lectura (`get pods`, `get nodes`, `get svc`, `get endpoints`, `logs`).

Un parámetro como `?pod=x;kubectl delete ns prod` se rechaza con `400` antes de salir hacia el clúster. Cubierto por `tests/unit/test_seguridad_endpoints.py`.

## Lectura de estados de Terraform

Un estado contiene los atributos completos de cada recurso, incluidas llaves de acceso y cadenas de conexión. `TfStateService` descarga cada estado en memoria, extrae **solo** `id` y `type` y descarta el resto sin registrarlo ni cachearlo (`tests/unit/test_tfstate.py::test_solo_se_extraen_ids_y_tipos`). Basta `Storage Blob Data Reader`; no le des escritura.

## Gestión de secretos

- Local: `backend/.env` (ignorado por git).
- Azure: **no hay secretos de Azure**. El API usa una identidad administrada asignada por el usuario (Reader y Storage Blob Data Reader). El único secreto opcional es la clave de Gemini, guardada como *secret* de la Container App.
- Mejora pendiente: referencias a Key Vault en lugar de valores en app settings (ver [roadmap](roadmap.md)).
- CI: [gitleaks](https://github.com/gitleaks/gitleaks) analiza cada push y PR.

## Endurecimiento de la infraestructura

- Container App con ingress HTTPS y sin acceso de administración expuesto.
- Storage con TLS 1.2 mínimo y sin acceso público a blobs.
- Contenedor del backend con usuario sin privilegios (`uid 10001`).
- nginx del panel (Docker) con `X-Content-Type-Options`, `X-Frame-Options` y `Referrer-Policy`.
- Static Web App con cabeceras en [`staticwebapp.config.json`](../frontend/public/staticwebapp.config.json): CSP restrictiva (scripts solo propios; conexiones solo al API en Container Apps y a Entra ID), HSTS, `X-Frame-Options: DENY`, `Referrer-Policy` y `Permissions-Policy`. Verificada con el emulador de Static Web Apps: cero violaciones de CSP.
- Imagen del API en GHCR, escaneada con Trivy en cada PR.

## Cadena de suministro

| Control | Dónde |
|---|---|
| Vulnerabilidades en dependencias de Python | `pip-audit` en CI |
| Vulnerabilidades en dependencias de npm | `npm audit --audit-level=high` en CI |
| Vulnerabilidades en la imagen | Trivy en CI (altas y críticas con corrección disponible) |
| Actualizaciones | Dependabot semanal para pip, npm, Actions, Docker y Terraform |
| Secretos en el código | gitleaks sobre todo el historial |
| Despliegue sin secretos | OIDC de GitHub Actions a una identidad con permisos solo sobre el grupo de recursos |

## Riesgos aceptados

| Riesgo | Por qué se acepta | Cómo se mitiga |
|---|---|---|
| Azure SQL admite conexiones desde cualquier servicio de Azure (regla `AllowAzureServices`, 0.0.0.0) | Container Apps de consumo no tiene IPs de salida fijas ni red virtual; un endpoint privado tiene costo fijo | Autenticación solo con Entra ID (sin usuarios SQL ni contraseñas): conectarse exige un token de una identidad con usuario en la base. TLS 1.2 mínimo. Las IPs de administración se abren por ejecución (`scripts/db-bootstrap.sh`) y se cierran al terminar |
| La cuenta de almacenamiento de datos admite acceso de red público (señalado por Infracost) | Container Apps en plan de consumo sin red virtual monta Azure Files por el endpoint público; desactivarlo rompe el almacenamiento de la plataforma | Acceso solo con la llave de la cuenta (que Terraform entrega a la Container App), TLS 1.2 mínimo y sin blobs públicos. La alternativa, un entorno con red virtual y endpoint privado, tiene costo fijo y queda como opción en el [plan](plan/05-infraestructura.md#red) |

## Reportar una vulnerabilidad

Ver [SECURITY.md](../SECURITY.md).

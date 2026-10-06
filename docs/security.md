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
- Azure: **no hay secretos de Azure**. El API usa una identidad administrada asignada por el usuario (Reader, Storage Blob Data Reader, AcrPull). El único secreto opcional es la clave de Gemini, guardada como *secret* de la Container App.
- Mejora pendiente: referencias a Key Vault en lugar de valores en app settings (ver [roadmap](roadmap.md)).
- CI: [gitleaks](https://github.com/gitleaks/gitleaks) analiza cada push y PR.

## Endurecimiento de la infraestructura

- Container App con ingress HTTPS y sin acceso de administración expuesto.
- Storage con TLS 1.2 mínimo y sin acceso público a blobs.
- Contenedor del backend con usuario sin privilegios (`uid 10001`).
- nginx del panel con `X-Content-Type-Options`, `X-Frame-Options` y `Referrer-Policy`.

## Reportar una vulnerabilidad

Ver [SECURITY.md](../SECURITY.md).

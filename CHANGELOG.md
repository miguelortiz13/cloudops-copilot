# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/); versionado [SemVer](https://semver.org/lang/es/).

## [Sin publicar]

### Cambiado
- Los endpoints reciben sus servicios por `Depends` con tipos (`app/core/deps.py`) en lugar de la tupla posicional `get_services()[n]`; el contenedor es un dataclass con nombres.

- `AzureClient` (`app/providers/azure/`): credenciales y Resource Graph salen del agente de chat. Los servicios y el generador de IaC dependen del cliente, no del agente; hay una sola instancia compartida.

### Añadido
- **Interfaz de modelos de lenguaje** (`app/llm`): los agentes piden texto con `llm.generar()` y no conocen el SDK. Gemini migra a `google-genai`, porque `google-generativeai` ya no tiene soporte y se retiró (la imagen baja de 533 a 366 MB). Las fallas llegan como `LLMError`, con respaldo por agente, y cada llamada registra uso, modelo, usuario, tokens y duración.
- **Límite de uso del modelo por usuario**: 30 consultas por hora y 150 por día, configurables. Responde 429 con `Retry-After` en el chat, el agente de Kubernetes y el generador de IaC; el bot de Teams avisa en el canal. El motor de reglas no cuenta.
- **Grupos de seguridad de Entra ID por rol** (Administradores, Operadores, Lectores), con miembros en la variable `role_members`. El rol sale del claim `groups` del token. En Entra ID Free Terraform además asigna el acceso a cada miembro, porque asignar grupos a una aplicación requiere P1.
- **Administración** en el panel (solo administradores): actividad de usuarios (auditoría con búsqueda y filtros), tu acceso y el origen de tu rol, y el estado de la base y de cada recolector.
- **Roles**: los app roles de Entra ID `CloudOps.Reader`, `CloudOps.Operator` y `CloudOps.Admin`. El backend los exige con `requiere()` y responde 403 si no alcanzan. Un usuario asignado sin rol es lector. `GET /api/me` devuelve el usuario y sus permisos, y el panel desactiva lo que el rol no permite.
- **Auditoría**: la tabla `audit_log` (migración `0002`) y una línea JSON en el log por cada acción que cambia algo o actúa sobre la nube. `GET /api/admin/audit` la expone a los administradores.
- **Base de datos**: Azure SQL Database con la oferta gratuita (pausa automática al agotar el cupo: USD 0), solo Entra ID, en centralus. Modelo canónico con SQLAlchemy (`app/db/models.py`: cuentas, recursos, costos diarios FOCUS, reglas, hallazgos con historial, KPIs diarios, ejecuciones de recolectores) y migraciones de Alembic.
- **Recolector diario** (`app/collectors/`, Container Apps Job `caj-<base>-collector`, 06:00 UTC): inventario con altas y bajas, costo diario por recurso y servicio (30 días la primera vez, después ventana móvil de 7), hallazgos con ciclo de vida (detectado, resuelto solo al dejar de detectarse, reabierto, aceptación vencida) y KPIs diarios. Cada ejecución queda en `collector_runs`.
- Modo estricto en `AzureClient.query_azure_resource_graph(raise_errors=True)` y `SecOpsService.build_report(strict=True)` (`failed_queries`): un error ya no se confunde con "sin resultados".
- `CostService.get_daily_cost_by_resource`: gasto diario por recurso y servicio.
- `scripts/db-bootstrap.sh`: migraciones y usuario de la identidad del API, con firewall abierto solo durante la ejecución.
- `GET /api/admin/database`: versión del esquema, filas por tabla y últimas ejecuciones de los recolectores.
- Pruebas de routers con servicios sustituidos (`tests/unit/test_routers.py`), incluidos el generador de IaC y el chat.

- **Cumplimiento** (reemplaza a la sección ISO 27001 del panel): estado de los controles de CIS Azure Foundations 2.0.0 e ISO/IEC 27001:2022 que evidencian las reglas, con evidencia directa o parcial. Un control cuya regla no se pudo evaluar queda "sin evidencia", nunca "cumple". Ver [docs/modules/compliance.md](docs/modules/compliance.md).
- **Catálogo de reglas** (`app/compliance/catalog.py`): una sola definición por regla, con descripción del riesgo, forma de detección, remediación, referencias y mapeo. El recolector la sincroniza en `rules`, y `SecOpsService` toma de ahí el título, la recomendación y los controles. Los hallazgos muestran los controles que incumplen.
- **Clasificación ISO de activos en la base** (paso `classification` del recolector, tabla `asset_classifications`, migración `0003`): misma regla que el Excel, ahora con el motivo de cada clasificación y custodio desde las tags o el creador. Un operador puede fijarla a mano con un motivo; el recolector la respeta y queda auditada. Exportación CSV.

- **Pruebas del panel**: Vitest para formato, caché de datos, cliente del API y la lógica de Cumplimiento y Gestión de hallazgos (permisos por rol, validaciones y lo que se envía al API). Playwright sobre el build de producción con el API simulado: todas las secciones, roles, flujos, errores y teléfono, y regresión visual con 12 capturas de datos ficticios generadas en la imagen oficial de Playwright. Nuevo job de CI `Frontend E2E (Playwright)`.

- **Capa de proveedores** (ADR 0006): contrato por capacidad en `app/providers/base.py` (modelo canónico; un fallo es un error, nunca un vacío; capacidades declaradas) y `AzureProvider`. Los recolectores de inventario, costos y hallazgos solo hablan con el proveedor; lo propio de Azure (uid de las reglas de NSG, consultas por regla, reintento ante el 429) vive en él. Pruebas de contrato (`tests/contract/`): la misma batería contra `AzureProvider` sobre respuestas grabadas de Resource Graph y Cost Management y contra un proveedor en memoria, que es el doble de las pruebas de los recolectores.

- **Cuentas conectadas** (Administración): qué ve la plataforma de cada nube y con qué permisos efectivos, según lo que el recolector logró leer y sin consultar la nube. Por cuenta: si sigue visible en el inventario, si entrega su gasto o le falta el rol de lectura de costos, recursos, hallazgos activos y gasto de 30 días. Por proveedor: capacidades activas, las que faltan con su motivo (por ejemplo, sin cuentas de estado de Terraform configuradas) y la identidad con la que se conecta. `GET /api/admin/accounts`.

### Eliminado
- `GET /api/governance/iso`, que leía la hoja `12_inventario_iso` del Excel del pipeline: la reemplazan `/api/compliance` y `/api/compliance/assets`.

### Rendimiento
- **Las vistas precalculadas vencían a los 58 minutos**: se calculaba "las 07:00 siguientes" y el recolector las escribe a las 06:02. Desde las 07:00 cada visita al panel despertaba la base (medido: 48 s y cupo gratuito consumido). Ahora valen hasta que termine la siguiente recolección, con la hora tomada de `collector_cron` (`COLLECTOR_HOUR_UTC`).
- **El API ya no precarga costos en cada arranque en frío** (3 min de consultas a Cost Management, con la réplica encendida y riesgo de 429). Lo hace el recolector diario (paso `costcache`) en el almacenamiento compartido; el API considera la caché vigente 26 h y relee el disco antes de consultar Cost Management.
- **Panel por secciones**: cada módulo se descarga al abrirlo (`React.lazy`). La carga inicial baja de 177 a 156 KB comprimidos; las secciones pesan de 1,5 a 6 KB.
- **Tendencia del inventario completa**: une la serie diaria de la base (recolector, sin huecos) con el JSONL anterior, que solo tenía los días con visitas. Sale de la vista precalculada, sin despertar la base. Los KPIs diarios incluyen además recursos productivos y no productivos.

### Corregido
- Cuentas conectadas mostraba "—" como gasto de una cuenta con permiso de costos y sin consumo en el periodo: si Cost Management respondió y no hubo filas, el gasto es cero.
- En un teléfono la ruta de navegación se montaba sobre el indicador de conexión (lo detectó la captura de regresión visual). Ahora muestra solo la sección actual.
- Administración mostraba con su código interno las acciones de clasificación de activos (`activo.clasificacion`). Ahora tienen su texto y su filtro.
- Los paneles laterales y los modales no tenían nombre accesible: ahora los lectores de pantalla anuncian su título.
- El recolector de costos dejaba "parcial" la ejecución cuando Cost Management respondía 429 para una suscripción (pasó dos días seguidos, con una suscripción distinta cada vez). Ahora la reintenta una vez tras 60 s, igual que la precarga de costos. Además solo guarda filas de las suscripciones cubiertas, cuya ventana sí se reemplazó.
- El motor de reglas del chat no entendía preguntas con tildes ("¿Cuántos recursos tengo?" respondía "No logré interpretar tu pregunta"). Ahora pregunta y palabras clave se comparan sin tildes ni mayúsculas.
- Algunas pruebas unitarias se conectaban a Azure con la sesión de `az login` de la máquina (al resolver los servicios reales antes de un 403). Ahora el cliente de Azure nunca se conecta en las pruebas unitarias.
- El agente de Kubernetes sin clave de Gemini respondía "Error IA: GEMINI_API_KEY missing". Ahora muestra el estado del clúster.
- La auditoría no guardaba en la base las acciones con fechas en el detalle (aceptar un riesgo con vencimiento): la columna JSON no serializa `date`. La acción se hacía y quedaba en el log, pero no en `audit_log`.
- Conectar a una base serverless que se está reanudando fallaba con un timeout de TCP (error 258 del driver), que no se reconocía como transitorio. Ahora se espera igual que con el error 40613.
- `/api/admin/database` respondía 500 sobre una base sin migrar.
- `azure_agent.py` cargaba el `.env` por su cuenta al importarse e ignoraba `CLOUDOPS_SKIP_DOTENV`.

## [2.4.2] — 2026-10-06

### Cambiado
- ESLint 10, `@eslint/js` 10, `globals` 17 y TypeScript 6.0. TypeScript 7 queda en espera hasta que typescript-eslint lo soporte (Dependabot lo ignora).
- Mínimos del backend: azure-identity 1.26, azure-mgmt-containerservice 41.7, azure-mgmt-resourcegraph 8.0.1, ruff 0.16.10.

### Eliminado
- `kubernetes`: no se usaba; el agente de Kubernetes opera AKS con run-command.

## [2.4.1] — 2026-10-06

### Cambiado
- React 19 en el panel. `useApi` y el generador de IaC derivan el estado de carga en lugar de fijarlo dentro de efectos (reglas nuevas de `eslint-plugin-react-hooks` 7).
- Terraform con azurerm 5.8 y azuread 3.10: `azurerm_federated_identity_credential` usa `user_assigned_identity_id`, `azurerm_storage_share` usa `storage_account_id` y el registro de proveedores pasa a `resource_provider_registrations = "none"`. Sin recursos recreados.
- La Container App conserva 5 revisiones inactivas (antes 100) y la cuenta de datos desactiva la replicación entre tenants (nuevo valor por defecto del proveedor).
- Acciones de GitHub en versiones con Node 24: checkout 7, setup-node 7, setup-python 7, docker/login-action 4, docker/build-push-action 7, azure/login 3, setup-terraform 4. Dependabot las agrupa en un solo PR.
- PyJWT ≥ 2.15.1, pytest ≥ 9.1.1, httpx ≥ 0.28.1; MSAL, lucide-react y typescript-eslint en sus últimas menores.

### Eliminado
- `pandas` y `azure-mgmt-resource`: no se usaban y pesaban en la imagen del API.

## [2.4.0] — 2026-10-06

### Añadido
- **Despliegue continuo** ([`cd.yml`](.github/workflows/cd.yml)): cada merge a `main` publica la imagen del API en GitHub Container Registry, actualiza la Container App, publica el panel y corre una prueba de humo. Azure se autentica por OIDC con una identidad administrada limitada al grupo de recursos (`infra/terraform/cicd.tf`); no hay secretos de larga vida.
- Escaneo de la cadena de suministro en CI: `pip-audit`, `npm audit` y Trivy sobre la imagen.
- Dependabot semanal para pip, npm, GitHub Actions, Docker y Terraform.
- Cabeceras de seguridad del panel en Static Web Apps: CSP, HSTS, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`.

### Cambiado
- La imagen del API vive en GHCR (pública) y ya no depende del ACR de otro proyecto; se eliminan el bloque `registry` y la asignación `AcrPull`.
- `scripts/deploy.sh` ya no construye imágenes: aplica Terraform, actualiza la imagen desde GHCR y publica el panel.

### Seguridad
- FastAPI 0.142, Starlette 1.7 y Pydantic 2.13: corrigen 16 vulnerabilidades conocidas en dependencias del API.
- Vite 8: `npm audit` sin hallazgos.

## [2.3.0] — 2026-10-06

### Cambiado
- **Rediseño completo del panel**: sistema de diseño con tokens (modo claro y oscuro), tipografía Inter, superficies sobrias con bordes finos; sin glassmorphism ni emojis en la interfaz.
- El frontend pasó de un `App.tsx` de 3.500 líneas con 453 estilos en línea a módulos por sección, componentes reutilizables y contratos tipados (`no-explicit-any` vuelve a ser error).
- **Costos primero, ahorro después**: el módulo de FinOps abre con la visión global del gasto y deja la optimización en una segunda pestaña.
- Navegación por hash con una URL por vista (`#/finops/ahorro`) y una página de **Resumen** ejecutivo como portada.
- Seguridad muestra la lista unificada de hallazgos priorizados, incluidas las reglas de SQL y HTTPS que el panel anterior no mostraba.
- Recursos sin uso unificados en una tabla con costo y origen de la cifra (facturado o estimado).
- La consola de agentes se sintoniza con la sección activa.

### Añadido
- `GET /api/finops/costs` (`CostOverviewService`): totales, comparación de periodos, mes en curso, proyección, serie diaria, desgloses y ranking.
- Respuestas del motor de reglas para los agentes de costos y seguridad (sin Gemini respondían con las reglas de inventario).
- Capturas en `docs/assets`.

### Corregido
- La exposición de SecOps sin scope explícito no consultaba costos y mostraba "sin gasto facturado".
- Textos de anomalías sin tildes.
- Efectos de React que devolvían la Promise de `scrollIntoView` en Chromium reciente y tumbaban la consola de agentes.

### Eliminado
- Respuestas simuladas del chat y datos de demostración en el panel cuando el API no responde: ahora se muestra el error.

## [2.2.0] — 2026-10-06

Primera versión probada y desplegada sobre un tenant real.

### Cambiado
- **Despliegue en Container Apps de consumo** (escala a cero) en lugar de App Service B1: costo fijo de ~13 USD/mes a ~0.
- **Identidad administrada** asignada por el usuario en lugar de client secrets: Reader en las suscripciones observadas, Storage Blob Data Reader en las cuentas de estados y AcrPull.
- **Entra ID gestionado por Terraform**: app registrations del API y del panel, preautorización y acceso restringido a usuarios asignados. El despliegue siempre activa `AUTH_ENABLED`.
- Esquema de tags por defecto `Environment` / `Project` / `ManagedBy`; showback por `Project` / `Environment`.
- `TFSTATE_ACCOUNT` acepta varias cuentas (`cuenta[/contenedor]`, separadas por comas); una cuenta inaccesible no invalida las demás.
- Los campos de tags del inventario y del CSV se derivan de `MANDATORY_TAGS` (`tagValues`).
- `deploy.sh` construye la imagen con Docker, aplica Terraform, compila el panel con la configuración de Entra ID y verifica el API.

### Añadido
- `scripts/smoke-test.sh` / `make smoke`: recorre el API desplegado con un token real y comprueba que sin token responda 401.
- `tests/conftest.py`: las pruebas no dependen del `.env` local ni de credenciales.
- Soporte de `AZURE_MANAGED_IDENTITY_CLIENT_ID` y `AZURE_CLI_TIMEOUT_SECONDS`.

### Corregido
- `/api/inventory/health` informaba `azureConnected: true` sin haber obtenido nunca un token; ahora la conexión se confirma al arrancar.
- La cobertura de Terraform contaba subrecursos, role assignments y budgets como recursos "obsoletos": 37 falsos positivos de 57 en un proyecto real.
- `ManagedBy=Manual` contaba como evidencia de IaC.
- El filtro `missingTags` en KQL devolvía todo el inventario para una tag no obligatoria y distinguía mayúsculas; ahora coincide con el camino en memoria (verificado con la prueba de integración).
- El chat interpretaba "dueño **de** X" buscando un recurso llamado `de`.
- Las tags faltantes se mostraban como `Managedby` en lugar de `ManagedBy`.

### Eliminado
- App Service y aprovisionamiento automático del bot de Teams (queda como paso manual opcional).

## [2.1.0] — 2026-10-05

Primera versión como proyecto independiente **CloudOps Copilot**.

### Cambiado
- Backend reorganizado como paquete `app/` (`core`, `agents`, `routers`, `services`, `schemas`). Se ejecuta con `uvicorn app.main:app`.
- Estado compartido extraído de `main.py` a `app/core/container.py`, eliminando el import circular `routers → main`.
- Configuración centralizada en `app/core/config.py`: tags obligatorias, dimensiones de showback, nombre de organización, URL del panel, directorio de datos, cuenta de tfstate y modelo de Gemini son variables de entorno.
- `DATA_DIR` reemplaza a `EXCEL_STORAGE_DIR` (que se sigue aceptando) y concentra todo lo persistente.
- Las consultas KQL de tags del agente se generan desde `MANDATORY_TAGS`.
- El generador de IaC usa el esquema de tags, la cuenta de estado y la región configurados.
- Terraform autocontenido: backend parcial (`backend.hcl`), nombres derivados de `name_prefix`, almacenamiento de datos propio, `azurerm_static_web_app`, outputs para el despliegue y bot opcional.
- `scripts/deploy.sh` toma los nombres de los outputs de Terraform; `destroy.sh` pide confirmación.
- Manifiesto de Teams convertido en plantilla con `package.sh`.
- Panel: URL del API y nombre de usuario por variables `VITE_*`.

### Añadido
- `pyproject.toml` (pytest y ruff), `requirements-dev.txt`, Dockerfiles, `docker-compose.yml`, `Makefile`.
- CI en GitHub Actions: ruff, pytest, eslint, build, `terraform validate`, gitleaks y build de imágenes.
- `scripts/bootstrap-state.sh` y `pipelines/inventory/scripts/bootstrap_workbook.py` (el pipeline ya no depende de un Excel preexistente).
- Documentación completa en `docs/`, incluidos ADR, política de tags y convención de nombres de referencia.

### Corregido
- `/api/governance/iso`, `/api/inventory/snapshots` y `/api/inventory/download` buscaban el Excel en `routers/inventory_pipeline/...`, una ruta inexistente.
- La alerta de SecOps de Teams mostraba cifras fijas de cuentas de almacenamiento y Key Vaults expuestos; ahora usa el reporte real.
- Errores de lint: variables sin usar en backend y frontend, bloques `catch` vacíos sin justificar.

### Eliminado
- Configuración, identificadores, datos de inventario, políticas y URLs de la organización original.
- `RecommendationsManager` (código muerto; los endpoints de recomendaciones ya eran stubs).
- Script `generate_icons.py` con rutas locales.

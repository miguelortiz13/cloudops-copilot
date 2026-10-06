# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/); versionado [SemVer](https://semver.org/lang/es/).

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

# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/); versionado [SemVer](https://semver.org/lang/es/).

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

# Guía de desarrollo

## Entorno

```bash
make setup     # backend/.venv + npm ci + backend/.env
make dev       # API con recarga en :8000, panel en :5173
```

## Convenciones

- **Idioma:** el dominio, los comentarios y la documentación están en español; los identificadores técnicos de frameworks se mantienen en inglés. En código nuevo, sigue el idioma del módulo que tocas.
- **Comentarios que explican el porqué.** El código existente documenta las decisiones con la medición que las motivó ("medido en un tenant real, esto señalaba el 90 %..."). Mantén ese estándar: un cambio de regla sin evidencia no se acepta.
- **Una definición por regla.** Si necesitas una regla de dominio, búscala en `governance.py`, `kql.py` o `pricing.py` antes de escribirla. Si no existe, créala ahí y consúmela desde el servicio y el agente.
- **Nada de valores de una organización en el código.** Todo lo que dependa del tenant va a `app/core/config.py` y al `.env`.
- **Procedencia de las cifras.** Si un número puede ser real o estimado, la respuesta debe decir cuál es.

## Estructura del backend

| Carpeta | Contiene | No contiene |
|---|---|---|
| `app/core` | Configuración y contenedor de servicios | Lógica de dominio |
| `app/routers` | Traducción HTTP ↔ servicios, validación de entrada | Consultas KQL, reglas |
| `app/services` | Reglas y acceso a Azure | Objetos de FastAPI |
| `app/agents` | Chat y generación de código | Reglas propias (las toma de `services`) |
| `app/schemas` | Contratos Pydantic | Lógica |

Los routers obtienen los servicios con `get_services()` de `app/core/container.py`. Es una tupla por compatibilidad con el código existente; migrarla a dependencias de FastAPI (`Depends`) está en el [roadmap](roadmap.md).

## Pruebas

`tests/conftest.py` aísla las pruebas: no leen tu `backend/.env`, no ven credenciales de Azure y fijan el esquema de tags que usan sus fixtures. Cada archivo lo importa también, así que funcionan igual con pytest o ejecutados como script.

```bash
make test               # backend/tests/unit — sin red, sin credenciales
make test-integration   # backend/tests/integration — contra un tenant real
```

| Archivo | Protege |
|---|---|
| `test_shadow_it.py` | La regla de cuatro señales y las claves de custodio |
| `test_tfstate.py` | Que solo se extraigan ids y tipos de los estados, y el cruce con el inventario |
| `test_finops_coverage.py` | Cobertura parcial de costos y showback solo sobre gasto facturado |
| `test_cost_cache_persistente.py` | Persistencia atómica y descarte de caché corrupta o vieja |
| `test_cost_warm_retry.py` | Segunda pasada de la precarga sin contar dos veces |
| `test_chat_cost_coherence.py` | Que el chat y el panel den el mismo costo y no inventen pronósticos |
| `test_contexto_agente.py` | Presupuesto de contexto y tags nulas |
| `test_risk_exposure.py` | Priorización severidad × dinero |
| `test_seguridad_endpoints.py` | Webhook de Teams y validación de comandos de Kubernetes |
| `integration/test_inventory_kpis.py` | Equivalencia exacta entre KPIs en KQL y en memoria |

Las pruebas unitarias sustituyen al agente de Azure por dobles en memoria, y también se pueden ejecutar como scripts: `.venv/bin/python tests/unit/test_shadow_it.py`.

## Calidad

```bash
make lint          # ruff (backend) + eslint (frontend)
make tf-validate   # terraform validate
```

La CI ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) ejecuta en cada push y PR: ruff y pytest, eslint y build del panel, `terraform fmt -check` y `validate`, gitleaks, `pip-audit` y `npm audit`, y el build de ambas imágenes con escaneo de Trivy. El despliegue continuo está en [`cd.yml`](../.github/workflows/cd.yml) (ver [despliegue](deployment.md#3-desplegar)), y Dependabot propone actualizaciones cada semana.

## Recetas

### Añadir una regla de seguridad

1. Escribe la consulta en `SecOpsService` (o en `kql.py` si el agente también la necesita) proyectando `id`, `name`, `resourceGroup`, `subscriptionId` y los campos que justifiquen el hallazgo.
2. Regístrala en `consultas` y llama a `agregar(...)` con tipo, título, función de severidad y recomendación.
3. Si el costo del recurso es atribuible al hallazgo, no hay que hacer nada más: `RiskService` lo cruza solo. Si no lo es (como en los NSG), márcalo `not_applicable` en `risk_service.py`.
4. Agrega un caso en `tests/unit/test_risk_exposure.py`.

### Añadir un endpoint

1. Router en `app/routers/<módulo>.py` con `APIRouter(tags=[...])`.
2. Schemas en `app/schemas`.
3. Si es un módulo nuevo, inclúyelo en la tupla de `app/main.py`.
4. Documenta la ruta en [api.md](api.md).

### Cambiar el esquema de tags

Solo configuración: `MANDATORY_TAGS` en `.env` y `mandatory_tags` en Terraform. Corre `make test-integration` para confirmar que los KPIs en KQL y en memoria siguen coincidiendo.

## Frontend

```
frontend/src/
├── App.tsx                 sesión de Entra ID, layout y enrutamiento por hash (#/finops/ahorro)
├── styles/tokens.css       tokens de diseño: colores, radios, sombras; modo claro y oscuro
├── styles/app.css          layout y componentes, escritos contra los tokens
├── lib/                    cliente del API con caché (useApi), tipos de los contratos, formato es-CO, markdown
├── state/                  contexto global: alcance de suscripciones, tema, avisos, consola de agentes
├── components/             ui (tarjetas, KPIs, tablas, drawer, modal), charts (SVG), layout, nav
└── modules/<sección>/      una página por sección: overview, inventory, finops, secops, iac, iso, reports
```

- **Sin valores sueltos de color**: todo sale de `tokens.css`. El modo oscuro redefine tokens; no hay una segunda hoja de estilos.
- **Contratos tipados** en `lib/types.ts`. `no-explicit-any` es error en ESLint.
- **Gráficos** propios en SVG (`components/charts.tsx`), siguiendo reglas fijas: columnas de 24 px como máximo con extremo redondeado de 4 px, separación de 2 px, cuadrícula de línea fina, tooltip y vista de tabla equivalente. La paleta de datos (slots 1-3) está validada para daltonismo en ambos modos.
- **Estado de carga**: `useApi` muestra lo último cargado mientras refresca (opacidad reducida), sin vaciar la pantalla.
- **Colores de estado reservados** (bueno, aviso, serio, crítico) y siempre con texto: una severidad nunca se comunica solo con color.

# 6. Seguridad, calidad y operación

## Autorización por rol

Hoy hay dos estados: tener acceso o no tenerlo. Al sumar acciones (lanzar recolectores, aceptar riesgos, abrir PRs) hacen falta roles, definidos como *app roles* de Entra ID y validados en el API.

| Capacidad | Lector | Operador | Administrador |
|---|---|---|---|
| Ver todas las vistas y exportar | ✓ | ✓ | ✓ |
| Preguntar a los agentes de inventario, costos y seguridad | ✓ | ✓ | ✓ |
| Agente de Kubernetes (ejecuta comandos de lectura en el clúster) | | ✓ | ✓ |
| Asumir hallazgos, generar HCL y abrir PRs | | ✓ | ✓ |
| Aceptar riesgos (con justificación y vencimiento) | | | ✓ |
| Reejecutar recolectores, conectar cuentas, configurar gobernanza | | | ✓ |
| Ver el registro de auditoría | | | ✓ |

Opcional en fase 4: alcance por cuenta o proyecto, para que un equipo solo vea lo suyo.

## Auditoría

Tabla `audit_log` de solo inserción, con quién, qué, sobre qué, cuándo, desde dónde y el resultado. Se registran todas las acciones que cambian estado (asumir, aceptar, abrir PR, reejecutar, cambiar configuración) y las consultas a agentes (sin el contenido de la respuesta). Se conserva 12 meses.

## Endurecimiento

| Control | Estado | Acción |
|---|---|---|
| Identidad administrada, sin secretos de Azure | Hecho | Extender a AWS por federación OIDC |
| CORS restringido y Entra ID obligatorio en el despliegue | Hecho | — |
| Validación de comandos de Kubernetes (RFC 1123, metacaracteres) | Hecho | Mantener con pruebas |
| Límite de tasa por usuario en `/api/chat` y `/api/k8s/chat` | Falta | Fase 1 |
| Cabeceras de seguridad en el panel (CSP, HSTS, frame-ancestors) | Falta | `staticwebapp.config.json`, fase 1 |
| Escaneo de dependencias (Dependabot, `pip-audit`, `npm audit`) | Falta | Fase 1, en CI |
| Escaneo de la imagen (Trivy) y SBOM | Falta | Fase 1, en CI |
| Secretos en Key Vault | Falta | Fase 1 |
| Pruebas de seguridad del API (autorización por rol en cada endpoint) | Parcial | Fase 1, una prueba por endpoint y rol |

## Estrategia de pruebas

| Nivel | Qué cubre | Herramienta | Cuándo corre |
|---|---|---|---|
| Unitarias | Reglas, normalización, cálculos de costos, ciclo de vida de hallazgos | pytest | Cada push |
| **Contrato de proveedor** | Cada proveedor devuelve el modelo canónico correcto a partir de respuestas grabadas de la nube | pytest + fixtures JSON | Cada push |
| Integración | Recolectores contra el tenant de laboratorio (Azure y AWS) | pytest con credenciales federadas | Nocturna |
| Fidelidad | KQL frente a memoria (existente) y totales de costo frente a la factura | pytest | Nocturna |
| Componentes | Componentes y vistas del panel | Vitest + Testing Library | Cada push |
| Extremo a extremo y regresión visual | Flujos principales y capturas comparadas | Playwright con datos anonimizados | Cada PR |
| Evaluación de agentes | Preguntas con respuesta verificable | Conjunto propio | Nocturna |
| Humo | Endpoints del despliegue con token real | `scripts/smoke-test.sh` | Tras cada despliegue |

Las pruebas de contrato con fixtures son las que permiten desarrollar el proveedor de AWS sin depender de una cuenta en cada push, y las que detectan cuándo una API de la nube cambia su respuesta.

## Objetivos de servicio

Para un uso interno, objetivos realistas que se puedan medir:

| SLO | Objetivo |
|---|---|
| Disponibilidad del API (respuestas no 5xx) | 99 % mensual |
| Latencia de las vistas servidas desde la base de datos | p95 < 1,5 s (excluye el arranque en frío) |
| Frescura del inventario | En vivo en la vista; historia con < 26 h |
| Frescura de hallazgos | < 26 h (ventana diaria) o en vivo bajo demanda |
| Frescura de los costos | < 30 h (las nubes consolidan con retraso) |
| Éxito de recolectores | ≥ 95 % de ejecuciones |

## Respaldo y recuperación

| Elemento | Respaldo | Recuperación |
|---|---|---|
| Infraestructura | Terraform en el repositorio | `terraform apply` |
| Base de datos | Backups automáticos de Azure SQL (punto en el tiempo) | Restauración desde el portal o la CLI |
| Datos de las nubes | Son reconstruibles: los recolectores los vuelven a leer | Reejecutar recolectores (los costos, hasta el límite de historia de cada export) |
| Configuración | Variables de Terraform y tablas de configuración | Incluida en lo anterior |

Objetivos: RPO de 24 h, RTO de 2 h. Lo único irrecuperable sin backup son el ciclo de vida de los hallazgos (dueños, aceptaciones) y la actividad de Azure con más de 14 días: por eso la base de datos necesita backups y la actividad debe guardarse desde la fase 1.

## Runbooks

Se documentan en `docs/runbooks/`:

- Un recolector falla de forma repetida.
- Cost Management o Cost Explorer devuelve 429 sostenidos.
- Rotación de la federación con AWS (cambio de tenant o de identidad).
- Restaurar la base de datos a un punto anterior.
- Revertir un despliegue.
- Incorporar una nueva cuenta de AWS a la organización observada.

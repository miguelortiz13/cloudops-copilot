# Flujos del sistema

Cinco flujos mueven la plataforma. El principal es el job diario, que lee las dos nubes y deja todo listo para el panel; los avisos y el reporte mensual son sus últimos pasos. Los componentes que aparecen aquí están descritos en [arquitectura](architecture.md).

## Job diario de recolección

Un Container Apps Job corre una vez al día (`collector_cron`, por defecto 06:00 UTC) y ejecuta 12 pasos en orden ([`app/collectors/run.py`](../backend/app/collectors/run.py)). Cada paso usa su propia transacción y deja su resultado en `collector_runs`: si uno falla (por ejemplo, AWS), los demás siguen y el job termina marcado con error.

```mermaid
flowchart LR
    subgraph L[1 · Leer y guardar]
      INV[inventory<br/>inventory_aws] --> CLS[classification<br/>ISO] --> CST[costs<br/>costs_aws] --> FND[findings<br/>findings_aws] --> KPI[kpis]
    end
    subgraph P[2 · Preparar el panel]
      CC[costcache<br/>costos en vivo] --> RM[readmodel<br/>vistas por defecto]
    end
    subgraph C[3 · Comunicar]
      REP[report<br/>reporte mensual] --> NOT[notify<br/>avisos]
    end
    KPI --> CC
    RM --> REP
    L --> SQL[(Azure SQL)]
    RM --> FS[(File Share)]
    REP & NOT --> WH[Webhook<br/>Discord · Slack · Teams]
```

- Los pasos `*_aws` solo corren si la federación con AWS está configurada.
- Un paso termina `ok`, `parcial` (parte del alcance no respondió; lo leído vale) o `error`. Administración muestra el último estado de cada uno.
- Reejecutar a mano: `az containerapp job start` sobre el job, o solo algunos pasos con `python -m app.collectors.run --only costs,findings`.

## Avisos (paso `notify`)

Detalle de los eventos en [avisos y reportes](modules/notifications-reports.md).

```mermaid
flowchart TD
    A[Marca de agua: until del último aviso correcto<br/>la primera vez, últimas 26 h] --> B[Hallazgos altos o críticos detectados,<br/>reabiertos o vencidos desde la marca]
    A --> C[Recolectores con dos fallas seguidas]
    D[Costos: anomalías de los últimos 3 días<br/>y presupuestos del mes] --> E{¿Clave ya enviada?<br/>detail.sent}
    E -- sí --> X[Se descarta]
    E -- no --> F
    B & C --> F{¿Hay algo que avisar?}
    F -- no --> OK[ok, sin envío]
    F -- sí --> G[Mensaje según el host:<br/>embed en Discord, texto en Slack,<br/>tarjeta adaptable en Teams]
    G --> H{¿El webhook respondió 2xx?}
    H -- sí --> I[ok: guarda until y las claves vigentes]
    H -- no --> J[error: el día siguiente reintenta lo mismo]
```

## Reporte mensual (paso `report`)

```mermaid
flowchart TD
    A{¿Día 4 o después?} -- no --> Z[ok, nada que hacer]
    A -- sí --> B{¿El mes anterior ya se envió?}
    B -- sí --> Z
    B -- no --> C{¿Hay datos de ese mes?}
    C -- no --> Z
    C -- sí --> D[Cifras del mes: gasto contra presupuesto,<br/>hallazgos, inventario, ejecuciones del job]
    D --> E{¿Discord?}
    E -- sí --> F[PDF adjunto]
    E -- no --> G[Resumen con enlace a Reportes]
    F & G --> H[Guarda el mes enviado]
```

Se espera al día 4 porque los costos llegan con hasta 72 h de retraso. Desde el panel se descarga el de cualquier mes (`GET /api/reports/monthly?month=AAAA-MM`).

## Inicio de sesión y autorización

```mermaid
sequenceDiagram
    participant U as Usuario
    participant P as Panel (MSAL)
    participant E as Entra ID
    participant A as API
    U->>P: abre el panel
    P->>E: token para api://…/access_as_user
    E-->>P: token con grupos (solo usuarios asignados)
    P->>A: petición con bearer token
    A->>A: valida firma, emisor, audiencia y expiración
    A->>A: rol = el mayor de sus grupos (lector, operador, administrador)
    A-->>P: respuesta, o 403 si el rol no alcanza
    A->>A: cada escritura queda en audit_log
```

Detalle en [seguridad](security.md#autenticación-del-api).

## Despliegue continuo

```mermaid
flowchart LR
    PR[Pull request] --> CI[CI: ruff · pytest · eslint · Vitest · build<br/>Playwright · Trivy · pip-audit · npm audit<br/>gitleaks · terraform validate]
    CI --> M{merge a main}
    M --> IMG[Imagen en GHCR]
    IMG --> API[Nueva revisión del API]
    API --> JOB[Imagen del job]
    JOB --> SWA[Panel en la Static Web App]
    SWA --> SMOKE[Prueba de humo]
```

GitHub Actions entra a Azure por OIDC, sin secretos guardados. La infraestructura se cambia aparte, con `terraform apply` manual ([operación](operations.md#cambios-de-infraestructura)).

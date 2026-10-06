# SecOps

Código: [`services/secops_service.py`](../../backend/app/services/secops_service.py), [`services/risk_service.py`](../../backend/app/services/risk_service.py), [`services/kql.py`](../../backend/app/services/kql.py).

## Hallazgos

| Tipo | Regla | Severidad |
|---|---|---|
| NSG | Puerto de administración (22, 3389, `*`) abierto a `0.0.0.0/0` o `*` | **Crítica** si el NSG está asociado y hay IPs públicas en el scope; si no, alta |
| Storage | `allowBlobPublicAccess == true` | Crítica sin firewall de red; si no, alta |
| Key Vault | Alcanzable desde red pública | Crítica sin firewall; si no, alta |
| SQL Server | `publicNetworkAccess` habilitado | Alta |
| App Service | Sin `httpsOnly` | Alta |
| Discos | Sin cifrado con llave gestionada por el cliente | Media |
| Cualquier recurso | `provisioningState == Failed` | Media |

Cada hallazgo incluye una recomendación concreta. La severidad por **alcanzabilidad** evita marcar igual una regla abierta en un NSG huérfano que una que expone una VM con IP pública.

## Exposición priorizada: severidad × dinero

`/api/secops/exposure` cruza cada hallazgo con el gasto facturado del recurso expuesto. Sin ese cruce, una cuenta de almacenamiento pública de 2.000 USD/mes y una de 3 USD se ven igual de urgentes.

- **La severidad manda y el dinero desempata**, nunca al revés: el costo mide el valor del activo, no la probabilidad de explotación.
- **El gasto expuesto se agrega por recurso**, no por hallazgo: un storage que viola dos reglas cuenta una vez, con su severidad más alta.
- **Nada se rellena con ceros**: un recurso sin cobertura de costo vale *desconocido* y se cuenta aparte. Las reglas de NSG se marcan `not_applicable`, porque lo que vale dinero son las máquinas de detrás y ese vínculo no se puede establecer de forma fiable desde Resource Graph.

El agente de SecOps del chat consume este mismo reporte, de modo que prioriza igual que el panel.

Pruebas: `tests/unit/test_risk_exposure.py`.

## Límites

Estas reglas cubren los hallazgos más frecuentes en tenants Azure; no sustituyen a Microsoft Defender for Cloud ni a un CSPM completo. Añadir una regla nueva: ver [development.md](../development.md#añadir-una-regla-de-seguridad).

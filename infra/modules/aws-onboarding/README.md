# aws-onboarding

Incorpora una organización de AWS a cloudops-copilot. Se aplica en la **cuenta
de administración** (o en una cuenta independiente) con una sesión de AWS que
tenga permisos de IAM, S3, Resource Explorer y Data Exports.

| Crea | Para | Costo |
|---|---|---|
| Proveedor OIDC de Entra ID y rol `<name>-reader` | La identidad administrada de la plataforma entra sin llaves (`AssumeRoleWithWebIdentity`) | USD 0 |
| Índice agregador y vista `<name>-inventario` de Resource Explorer | Inventario de todas las regiones indexadas en una búsqueda | USD 0 |
| Bucket privado y export FOCUS 1.2 (Data Exports) | Costos de toda la organización | Centavos de S3 |
| Base y tabla de Glue con proyección de particiones, workgroup de Athena con tope de bytes por consulta | La plataforma consulta el export sin crawler | USD 5 por TB leído; en una cuenta pequeña, menos de un centavo al mes |

Permisos del rol: `SecurityAudit` y `ViewOnlyAccess`, más una política propia
(listado y búsqueda solo en la vista, `tag:GetResources`, `cloudtrail:LookupEvents`,
lectura de la organización y de presupuestos). Sin `ReadOnlyAccess` ni
`s3:GetObject`: metadatos, no datos.

```hcl
module "aws_onboarding" {
  source              = "../modules/aws-onboarding"
  name                = "cloudops-dev"
  oidc_issuer         = "sts.windows.net/<tenant>/"      # tokens v1 de Entra ID
  audience            = "api://<client id del registro>" # URI del registro de federación
  principal_object_id = "<object id de la identidad administrada>"
}
```

Antes del primer apply:

- **Resource Explorer** viene activo en muchas cuentas. Si la región ya tiene
  índice, importarlo:
  `terraform import 'module.aws_onboarding[0].aws_resourceexplorer2_index.aggregator' <arn>`.
  El tipo del índice se puede cambiar una vez cada 24 horas, y la réplica de
  las demás regiones al agregador tarda algunas horas.
- **Export de costos:** la primera entrega tarda hasta 24 horas. `cost_export =
  false` en cuentas miembro (el de la cuenta de administración cubre a todas).

La tabla declara solo las columnas que lee la plataforma (fecha, cuenta,
recurso, servicio, costo facturado y efectivo, moneda); Parquet las resuelve
por nombre. El rol las lee con su propia política (Athena del workgroup, Glue
de esa base y `s3:GetObject` solo sobre el export y los resultados).

Pendiente (docs/plan/07-hoja-de-ruta.md): rol de lectura en cuentas miembro
con un StackSet.

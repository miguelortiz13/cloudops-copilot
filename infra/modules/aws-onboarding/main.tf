# ---------------------------------------------------------------------------
# Incorporación de una organización de AWS a cloudops-copilot (fase 2, paso 2)
# ---------------------------------------------------------------------------
#
# Se aplica en la cuenta de administración de la organización:
# - Proveedor OIDC de Entra ID y rol hub de solo lectura que asume la
#   identidad administrada de la plataforma, sin llaves (paso 1).
# - Vista propia de Resource Explorer sobre el índice agregador: inventario
#   de todas las regiones indexadas.
# - Export de costos FOCUS 1.2 (Data Exports) a un bucket privado.
#
# Pendiente: rol de lectura en cuentas miembro con un StackSet (necesita una
# cuenta miembro de laboratorio) y Athena para consultar el export (paso 4).
# Detalle: docs/plan/03-multicloud.md.

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.region
  partition  = data.aws_partition.current.partition
}

# ---------------------------------------------------------------------------
# Identidad: federación OIDC y rol hub
# ---------------------------------------------------------------------------
resource "aws_iam_openid_connect_provider" "entra" {
  url            = "https://${var.oidc_issuer}"
  client_id_list = [var.audience]
  tags           = var.tags
}

resource "aws_iam_role" "hub" {
  name                 = "${var.name}-reader"
  description          = "Solo lectura de metadatos para cloudops-copilot; lo asume la identidad administrada de Azure por OIDC."
  max_session_duration = 3600
  tags                 = var.tags

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.entra.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${var.oidc_issuer}:aud" = var.audience
          # Obligatoria: sin ella cualquier aplicación del tenant asumiría el rol.
          "${var.oidc_issuer}:sub" = var.principal_object_id
        }
      }
    }]
  })
}

# Configuración y metadatos, sin leer datos: ReadOnlyAccess no sirve porque
# permite s3:GetObject y similares.
resource "aws_iam_role_policy_attachment" "hub" {
  for_each   = toset(["SecurityAudit", "job-function/ViewOnlyAccess"])
  role       = aws_iam_role.hub.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/${each.value}"
}

# Lo propio de la plataforma que las administradas no cubren o cubren de más.
resource "aws_iam_role_policy" "hub" {
  name = "cloudops-platform"
  role = aws_iam_role.hub.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid    = "Inventario", Effect = "Allow",
        Action = ["resource-explorer-2:Search", "resource-explorer-2:GetView"],
      Resource = aws_resourceexplorer2_view.cloudops.arn },
      { Sid = "Etiquetas", Effect = "Allow", Action = ["tag:GetResources"], Resource = "*" },
      { Sid = "Actividad", Effect = "Allow", Action = ["cloudtrail:LookupEvents"], Resource = "*" },
      { Sid    = "Organizacion", Effect = "Allow",
        Action = ["organizations:DescribeOrganization", "organizations:ListAccounts", "organizations:ListParents"],
      Resource = "*" },
      { Sid = "Presupuestos", Effect = "Allow", Action = ["budgets:ViewBudget"], Resource = "*" },
    ]
  })
}

# ---------------------------------------------------------------------------
# Inventario: Resource Explorer
# ---------------------------------------------------------------------------
# El índice de la región principal pasa a agregador: replica los de las demás
# regiones y una sola búsqueda las cubre. AWS lo activa solo en muchas cuentas;
# si ya existe, importarlo antes del apply:
#   terraform import 'module.aws_onboarding[0].aws_resourceexplorer2_index.aggregator' <arn del índice>
# Cambiar el tipo del índice solo se permite una vez cada 24 horas.
resource "aws_resourceexplorer2_index" "aggregator" {
  type = "AGGREGATOR"
  tags = var.tags
}

# Vista propia (no la predeterminada de la cuenta, que otros pueden cambiar).
resource "aws_resourceexplorer2_view" "cloudops" {
  name = "${var.name}-inventario"
  tags = var.tags

  included_property {
    name = "tags"
  }

  depends_on = [aws_resourceexplorer2_index.aggregator]
}

# ---------------------------------------------------------------------------
# Costos: export FOCUS 1.2 a S3 (Data Exports)
# ---------------------------------------------------------------------------
locals {
  # Todas las columnas de FOCUS_1_2_AWS (aws bcm-data-exports get-table): el
  # export exige listarlas.
  focus_columns = [
    "AvailabilityZone", "BilledCost", "BillingAccountId", "BillingAccountName", "BillingAccountType",
    "BillingCurrency", "BillingPeriodEnd", "BillingPeriodStart", "CapacityReservationId",
    "CapacityReservationStatus", "ChargeCategory", "ChargeClass", "ChargeDescription", "ChargeFrequency",
    "ChargePeriodEnd", "ChargePeriodStart", "CommitmentDiscountCategory", "CommitmentDiscountId",
    "CommitmentDiscountName", "CommitmentDiscountQuantity", "CommitmentDiscountType",
    "CommitmentDiscountStatus", "CommitmentDiscountUnit", "ConsumedQuantity", "ConsumedUnit",
    "ContractedCost", "ContractedUnitPrice", "EffectiveCost", "InvoiceId", "InvoiceIssuerName", "ListCost",
    "ListUnitPrice", "PricingCategory", "PricingCurrency", "PricingCurrencyContractedUnitPrice",
    "PricingCurrencyEffectiveCost", "PricingCurrencyListUnitPrice", "PricingQuantity", "PricingUnit",
    "ProviderName", "PublisherName", "RegionId", "RegionName", "ResourceId", "ResourceName", "ResourceType",
    "ServiceCategory", "ServiceName", "ServiceSubcategory", "SkuId", "SkuPriceDetails", "SkuPriceId",
    "SkuMeter", "SubAccountId", "SubAccountName", "SubAccountType", "Tags", "x_Discounts", "x_Operation",
    "x_ServiceCode",
  ]
  export_name = "${var.name}-focus"
}

resource "aws_s3_bucket" "costs" {
  count  = var.cost_export ? 1 : 0
  bucket = "${var.name}-costs-${local.account_id}"
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "costs" {
  count                   = var.cost_export ? 1 : 0
  bucket                  = aws_s3_bucket.costs[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "costs" {
  count  = var.cost_export ? 1 : 0
  bucket = aws_s3_bucket.costs[0].id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Solo el servicio de exports escribe, y solo para exports de esta cuenta.
resource "aws_s3_bucket_policy" "costs" {
  count  = var.cost_export ? 1 : 0
  bucket = aws_s3_bucket.costs[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DataExports"
        Effect    = "Allow"
        Principal = { Service = ["bcm-data-exports.amazonaws.com", "billingreports.amazonaws.com"] }
        Action    = ["s3:PutObject", "s3:GetBucketPolicy"]
        Resource  = [aws_s3_bucket.costs[0].arn, "${aws_s3_bucket.costs[0].arn}/*"]
        Condition = {
          StringLike = {
            "aws:SourceAccount" = local.account_id
            "aws:SourceArn" = [
              "arn:${local.partition}:cur:us-east-1:${local.account_id}:definition/*",
              "arn:${local.partition}:bcm-data-exports:us-east-1:${local.account_id}:export/*",
            ]
          }
        }
      },
      {
        Sid       = "SoloTLS"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.costs[0].arn, "${aws_s3_bucket.costs[0].arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.costs]
}

# El export no cuesta; el almacenamiento en S3 de una cuenta pequeña, centavos.
# La primera entrega tarda hasta 24 horas.
resource "aws_bcmdataexports_export" "focus" {
  count = var.cost_export ? 1 : 0
  tags  = var.tags

  export {
    name        = local.export_name
    description = "Costos en FOCUS 1.2 para cloudops-copilot."

    data_query {
      query_statement = "SELECT ${join(", ", local.focus_columns)} FROM FOCUS_1_2_AWS"
    }

    destination_configurations {
      s3_destination {
        s3_bucket = aws_s3_bucket.costs[0].bucket
        s3_prefix = "focus"
        s3_region = aws_s3_bucket.costs[0].region

        s3_output_configurations {
          compression = "PARQUET"
          format      = "PARQUET"
          output_type = "CUSTOM"
          overwrite   = "OVERWRITE_REPORT"
        }
      }
    }

    refresh_cadence {
      frequency = "SYNCHRONOUS"
    }
  }

  depends_on = [aws_s3_bucket_policy.costs]
}

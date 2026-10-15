output "role_arn" {
  description = "Rol hub que asume la identidad administrada."
  value       = aws_iam_role.hub.arn
}

output "inventory_view_arn" {
  description = "Vista de Resource Explorer de la plataforma."
  value       = aws_resourceexplorer2_view.cloudops.arn
}

output "cost_export" {
  description = "Bucket, prefijo y nombre del export FOCUS (null si no se crea)."
  value = var.cost_export ? {
    bucket = aws_s3_bucket.costs[0].bucket
    prefix = "focus"
    name   = local.export_name
    # Consulta con Athena (app/providers/aws).
    database  = aws_glue_catalog_database.costs[0].name
    table     = aws_glue_catalog_table.focus[0].name
    workgroup = aws_athena_workgroup.costs[0].name
  } : null
}

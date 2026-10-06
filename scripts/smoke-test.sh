#!/usr/bin/env bash
# Prueba de humo del API desplegado: obtiene un token de Entra ID con la sesion
# de Azure CLI (preautorizada en el API) y recorre los modulos principales.
#
# Uso: ./scripts/smoke-test.sh            (lee la URL y el scope de Terraform)
#      API_URL=... API_SCOPE=... ./scripts/smoke-test.sh
set -euo pipefail

TF_DIR="$(cd "$(dirname "$0")/.." && pwd)/infra/terraform"
API_URL="${API_URL:-$(terraform -chdir="$TF_DIR" output -raw api_url)}"
API_SCOPE="${API_SCOPE:-$(terraform -chdir="$TF_DIR" output -raw api_scope)}"
TOKEN=$(az account get-access-token --scope "$API_SCOPE" --query accessToken -o tsv)

fallos=0
probar() {
  local metodo=$1 ruta=$2 cuerpo=${3:-}
  local args=(-s -m 300 -o /dev/null -w "%{http_code} %{time_total}s" -X "$metodo"
              -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json")
  [ -n "$cuerpo" ] && args+=(-d "$cuerpo")
  local r; r=$(curl "${args[@]}" "$API_URL$ruta")
  printf '  %-6s %-36s %s\n' "$metodo" "$ruta" "$r"
  [[ $r == 200* ]] || fallos=$((fallos + 1))
}

echo "API: $API_URL"
probar GET  /api/inventory/health
probar GET  /api/inventory/subscriptions
probar POST /api/inventory/summary         '{"subscriptionIds":[]}'
probar POST /api/inventory/tag-compliance  '{"subscriptionIds":[]}'
probar POST /api/inventory/resources       '{"subscriptionIds":[],"pageSize":10}'
probar POST /api/iac/terraform-coverage    '{"subscriptionIds":[]}'
probar GET  /api/secops/report
probar GET  /api/finops/costs
probar GET  /api/finops/report
probar POST /api/chat                      '{"message":"resumen del inventario","agent_type":"inventory"}'

sin_token=$(curl -s -m 60 -o /dev/null -w "%{http_code}" "$API_URL/api/inventory/subscriptions")
printf '  %-6s %-36s %s (esperado 401)\n' GET "/api/inventory/subscriptions sin token" "$sin_token"
[ "$sin_token" = "401" ] || fallos=$((fallos + 1))

[ "$fallos" -eq 0 ] && echo "OK" || { echo "$fallos comprobacion(es) fallaron"; exit 1; }

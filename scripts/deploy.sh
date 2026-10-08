#!/usr/bin/env bash
# Despliegue manual en Azure (el habitual es el workflow CD de GitHub Actions):
#   1. infraestructura (terraform apply)
#   2. imagen del API: la que construyó la CI en GitHub Container Registry
#   3. panel (build con la configuracion de Entra ID + Static Web App)
#
# La imagen se elige con API_IMAGE (por defecto, la ultima de main).
# Requisitos: az login, terraform >= 1.5, node 20+.
# Configuracion: infra/terraform/terraform.tfvars y infra/terraform/backend.hcl
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF_DIR="$ROOT/infra/terraform"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

step() { echo -e "\n${YELLOW}$1${NC}"; }
fail() { echo -e "${RED}$1${NC}"; exit 1; }

for cmd in az terraform npm; do
  command -v "$cmd" >/dev/null || fail "Falta '$cmd' en el PATH."
done
[ -f "$TF_DIR/terraform.tfvars" ] || fail "Falta $TF_DIR/terraform.tfvars (copiar de terraform.tfvars.example)."
[ -f "$TF_DIR/backend.hcl" ] || fail "Falta $TF_DIR/backend.hcl (ejecutar scripts/bootstrap-state.sh)."

API_IMAGE="${API_IMAGE:-ghcr.io/miguelortiz13/cloudops-copilot-api:latest}"

step "[1/4] Infraestructura (terraform apply)"
terraform -chdir="$TF_DIR" init -input=false -backend-config=backend.hcl >/dev/null
# api_image solo se usa al crear la Container App; despues Terraform la ignora
# y la imagen se actualiza en el paso siguiente.
terraform -chdir="$TF_DIR" apply -input=false -var "api_image=$API_IMAGE" ${AUTO_APPROVE:+-auto-approve}

out() { terraform -chdir="$TF_DIR" output -raw "$1"; }
API_URL=$(out api_url)
FRONTEND_URL=$(out frontend_url)

step "[2/4] Imagen del API y del recolector: $API_IMAGE"
az containerapp update --name "$(out api_container_app_name)" \
  --resource-group "$(out resource_group_name)" --image "$API_IMAGE" --output none
az containerapp job update --name "$(out collector_job_name)" \
  --resource-group "$(out resource_group_name)" --image "$API_IMAGE" --output none

step "[3/4] Compilando el panel"
npm ci --prefix "$ROOT/frontend" --no-audit --no-fund >/dev/null
VITE_API_URL="$API_URL" \
VITE_AZURE_AD_CLIENT_ID="$(out spa_client_id)" \
VITE_AZURE_AD_TENANT_ID="$(out tenant_id)" \
VITE_API_SCOPE="$(out api_scope)" \
VITE_USER_DISPLAY_NAME="${VITE_USER_DISPLAY_NAME:-Operador}" \
  npm run build --prefix "$ROOT/frontend"

step "[4/4] Publicando el panel"
npx --yes @azure/static-web-apps-cli@2 deploy "$ROOT/frontend/dist" \
  --deployment-token "$(out static_web_app_api_key)" --env production

step "Verificando el API (el primer arranque desde cero tarda unos segundos)"
for _ in $(seq 1 30); do
  if curl -fsS -m 30 "$API_URL/api/inventory/health" >/dev/null 2>&1; then break; fi
  sleep 10
done
curl -sS -m 30 "$API_URL/api/inventory/health"; echo

echo -e "\n${GREEN}Despliegue completado.${NC}"
echo "  API:    $API_URL"
echo "  Panel:  $FRONTEND_URL"

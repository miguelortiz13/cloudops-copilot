#!/usr/bin/env bash
# Despliegue completo en Azure: infraestructura (Terraform), backend (zip deploy
# a App Service) y frontend (Static Web App).
#
# Requisitos: az login, terraform >= 1.5, node 20+, zip.
# Configuracion: infra/terraform/terraform.tfvars y infra/terraform/backend.hcl
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF_DIR="$ROOT/infra/terraform"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

step() { echo -e "\n${YELLOW}$1${NC}"; }
fail() { echo -e "${RED}$1${NC}"; exit 1; }

for cmd in az terraform npm zip; do
  command -v "$cmd" >/dev/null || fail "Falta '$cmd' en el PATH."
done
[ -f "$TF_DIR/terraform.tfvars" ] || fail "Falta $TF_DIR/terraform.tfvars (copiar de terraform.tfvars.example)."
[ -f "$TF_DIR/backend.hcl" ] || fail "Falta $TF_DIR/backend.hcl (copiar de backend.hcl.example)."

step "[1/5] Infraestructura (terraform apply)"
terraform -chdir="$TF_DIR" init -input=false -backend-config=backend.hcl
terraform -chdir="$TF_DIR" apply -input=false ${AUTO_APPROVE:+-auto-approve}

RG=$(terraform -chdir="$TF_DIR" output -raw resource_group_name)
API_APP=$(terraform -chdir="$TF_DIR" output -raw api_app_name)
API_URL=$(terraform -chdir="$TF_DIR" output -raw api_url)
SWA_TOKEN=$(terraform -chdir="$TF_DIR" output -raw static_web_app_api_key)
FRONTEND_URL=$(terraform -chdir="$TF_DIR" output -raw frontend_url)

step "[2/5] Empaquetando backend"
ARTIFACT="$(mktemp -d)/backend.zip"
(cd "$ROOT/backend" && zip -qr "$ARTIFACT" requirements.txt app pipelines \
   -x '**/__pycache__/*' '**/.venv/*')

# main.py importa sus routers y servicios como paquetes: si uno se queda fuera
# del zip, App Service arranca, falla el import y responde 500 sin que el
# despliegue de error. Se comprueba antes de subir nada.
for paquete in app/core app/routers app/services app/schemas app/agents; do
  unzip -l "$ARTIFACT" | grep -q "$paquete/" || fail "El paquete $paquete no esta en el artefacto."
done

step "[3/5] Desplegando backend en $API_APP"
az webapp deploy --resource-group "$RG" --name "$API_APP" --src-path "$ARTIFACT" --type zip
rm -f "$ARTIFACT"

step "[4/5] Compilando frontend"
npm ci --prefix "$ROOT/frontend" --no-audit --no-fund
VITE_API_URL="$API_URL" npm run build --prefix "$ROOT/frontend"

step "[5/5] Publicando frontend"
npx --yes @azure/static-web-apps-cli deploy "$ROOT/frontend/dist" \
  --deployment-token "$SWA_TOKEN" --env production

echo -e "\n${GREEN}Despliegue completado.${NC}"
echo "  API:    $API_URL"
echo "  Panel:  $FRONTEND_URL"

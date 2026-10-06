#!/usr/bin/env bash
# Prepara (una sola vez) la suscripcion de despliegue:
# - registra los proveedores de recursos que usa la plataforma;
# - crea la cuenta de almacenamiento del estado de Terraform;
# - escribe infra/terraform/backend.hcl.
#
# Uso: SUBSCRIPTION_ID=<id> [LOCATION=eastus2] [STATE_RG=rg-cloudops-tfstate] \
#      [STATE_ACCOUNT=<nombre unico>] ./scripts/bootstrap-state.sh
set -euo pipefail

: "${SUBSCRIPTION_ID:?Define SUBSCRIPTION_ID}"
LOCATION="${LOCATION:-eastus2}"
STATE_RG="${STATE_RG:-rg-cloudops-tfstate}"
# Los nombres de cuenta son unicos en todo Azure: sufijo derivado de la suscripcion.
STATE_ACCOUNT="${STATE_ACCOUNT:-sttfcloudops${SUBSCRIPTION_ID:0:6}}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
TF_DIR="$(cd "$(dirname "$0")/.." && pwd)/infra/terraform"

az account set --subscription "$SUBSCRIPTION_ID"

for ns in Microsoft.App Microsoft.Web Microsoft.Storage Microsoft.ManagedIdentity Microsoft.ContainerRegistry; do
  az provider register --namespace "$ns" --output none
done

az group create --name "$STATE_RG" --location "$LOCATION" \
  --tags Environment=shared Project=cloudops ManagedBy=Script --output none
az storage account create --name "$STATE_ACCOUNT" --resource-group "$STATE_RG" \
  --location "$LOCATION" --sku Standard_LRS --min-tls-version TLS1_2 \
  --allow-blob-public-access false \
  --tags Environment=shared Project=cloudops ManagedBy=Script --output none

# El usuario actual escribe el estado con su identidad (use_azuread_auth).
USER_ID=$(az ad signed-in-user show --query id -o tsv)
SCOPE=$(az storage account show --name "$STATE_ACCOUNT" --resource-group "$STATE_RG" --query id -o tsv)
az role assignment create --assignee-object-id "$USER_ID" --assignee-principal-type User \
  --role "Storage Blob Data Contributor" --scope "$SCOPE" --output none || true

# La asignacion de rol tarda en propagarse; se reintenta la creacion del contenedor.
for _ in $(seq 1 12); do
  az storage container create --name tfstate --account-name "$STATE_ACCOUNT" \
    --auth-mode login --output none 2>/dev/null && break
  sleep 10
done

cat > "$TF_DIR/backend.hcl" <<HCL
subscription_id      = "$SUBSCRIPTION_ID"
resource_group_name  = "$STATE_RG"
storage_account_name = "$STATE_ACCOUNT"
container_name       = "tfstate"
key                  = "cloudops-copilot/$ENVIRONMENT.terraform.tfstate"
use_azuread_auth     = true
HCL
echo "Estado listo en $STATE_ACCOUNT. Escrito $TF_DIR/backend.hcl"

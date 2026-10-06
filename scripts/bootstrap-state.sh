#!/usr/bin/env bash
# Crea (una sola vez) la cuenta de almacenamiento para el estado de Terraform de
# la plataforma y escribe infra/terraform/backend.hcl.
#
# Uso: SUBSCRIPTION_ID=<id> [LOCATION=eastus2] [STATE_RG=rg-tfstate] \
#      [STATE_ACCOUNT=sttfstatecloudops] ./scripts/bootstrap-state.sh
set -euo pipefail

: "${SUBSCRIPTION_ID:?Define SUBSCRIPTION_ID}"
LOCATION="${LOCATION:-eastus2}"
STATE_RG="${STATE_RG:-rg-tfstate}"
STATE_ACCOUNT="${STATE_ACCOUNT:-sttfstatecloudops}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
TF_DIR="$(cd "$(dirname "$0")/.." && pwd)/infra/terraform"

az account set --subscription "$SUBSCRIPTION_ID"
az group create --name "$STATE_RG" --location "$LOCATION" --output none
az storage account create --name "$STATE_ACCOUNT" --resource-group "$STATE_RG" \
  --location "$LOCATION" --sku Standard_LRS --min-tls-version TLS1_2 \
  --allow-blob-public-access false --output none
az storage container create --name tfstate --account-name "$STATE_ACCOUNT" \
  --auth-mode login --output none

# El usuario actual necesita escribir blobs con su identidad (use_azuread_auth).
USER_ID=$(az ad signed-in-user show --query id -o tsv)
SCOPE=$(az storage account show --name "$STATE_ACCOUNT" --resource-group "$STATE_RG" --query id -o tsv)
az role assignment create --assignee "$USER_ID" --role "Storage Blob Data Contributor" \
  --scope "$SCOPE" --output none || true

cat > "$TF_DIR/backend.hcl" <<HCL
subscription_id      = "$SUBSCRIPTION_ID"
resource_group_name  = "$STATE_RG"
storage_account_name = "$STATE_ACCOUNT"
container_name       = "tfstate"
key                  = "cloudops-copilot/$ENVIRONMENT.terraform.tfstate"
use_azuread_auth     = true
HCL
echo "Estado listo. Escrito $TF_DIR/backend.hcl"

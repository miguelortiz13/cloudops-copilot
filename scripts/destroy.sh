#!/usr/bin/env bash
# Elimina toda la infraestructura de la plataforma creada por Terraform,
# incluidos los registros de aplicacion de Entra ID.
#
# ATENCION: borra tambien la cuenta de datos (cache de costos, historico de
# KPIs, Excel y snapshots). La imagen en el ACR y el estado de Terraform se
# conservan.
set -euo pipefail

TF_DIR="$(cd "$(dirname "$0")/.." && pwd)/infra/terraform"

if [ "${AUTO_APPROVE:-}" != "1" ]; then
  read -r -p "Esto destruye todos los recursos de la plataforma, incluidos sus datos. Escribe 'destruir' para continuar: " ok
  [ "$ok" = "destruir" ] || { echo "Cancelado."; exit 1; }
fi

terraform -chdir="$TF_DIR" init -input=false -backend-config=backend.hcl >/dev/null
# api_image es obligatoria pero irrelevante al destruir.
terraform -chdir="$TF_DIR" destroy -input=false -var "api_image=destroy" ${AUTO_APPROVE:+-auto-approve}
echo "Infraestructura destruida."

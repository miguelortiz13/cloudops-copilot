#!/usr/bin/env bash
# Elimina toda la infraestructura de la plataforma creada por Terraform.
#
# ATENCION: borra tambien la cuenta de almacenamiento de datos (cache de costos,
# historico de KPIs, Excel y snapshots). Descarga lo que quieras conservar antes.
set -euo pipefail

TF_DIR="$(cd "$(dirname "$0")/.." && pwd)/infra/terraform"

if [ "${AUTO_APPROVE:-}" != "1" ]; then
  read -r -p "Esto destruye todos los recursos de la plataforma, incluidos sus datos. Escribe 'destruir' para continuar: " ok
  [ "$ok" = "destruir" ] || { echo "Cancelado."; exit 1; }
fi

terraform -chdir="$TF_DIR" init -input=false -backend-config=backend.hcl
terraform -chdir="$TF_DIR" destroy -input=false ${AUTO_APPROVE:+-auto-approve}
echo "Infraestructura destruida."

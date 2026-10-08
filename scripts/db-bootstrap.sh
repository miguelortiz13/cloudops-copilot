#!/usr/bin/env bash
# Prepara la base de datos de la plataforma (se ejecuta una vez y cada vez que
# haya migraciones nuevas; es idempotente):
#   1. abre el firewall de Azure SQL solo para la IP de quien lo ejecuta
#   2. aplica las migraciones (alembic upgrade head)
#   3. da acceso a la identidad administrada del API como usuario de Entra ID
#      con lectura, escritura y DDL (el recolector aplica migraciones)
#   4. cierra el firewall, también si algo falla
#
# Lo ejecuta el administrador de Entra ID del servidor (quien aplicó
# Terraform). No hay contraseñas: todo es con la sesión de `az login`.
# Requisitos: az login, terraform, Python con backend/requirements.txt.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF_DIR="$ROOT/infra/terraform"
PY="${PYTHON:-$ROOT/backend/.venv/bin/python}"
[ -x "$PY" ] || PY=python3

out() { terraform -chdir="$TF_DIR" output -raw "$1"; }
SERVER_FQDN="$(out sql_server_fqdn)"
SERVER="${SERVER_FQDN%%.*}"
DB="$(out sql_database_name)"
RG="$(out resource_group_name)"
IDENTITY="$(out api_identity_name)"
RULE="bootstrap-$(date +%s)"

IP="$(curl -fsS https://api.ipify.org)"
echo "[1/4] Firewall: regla temporal para la IP actual"
az sql server firewall-rule create -g "$RG" -s "$SERVER" -n "$RULE" \
  --start-ip-address "$IP" --end-ip-address "$IP" -o none
trap 'echo "[4/4] Firewall: retirando la regla temporal"; az sql server firewall-rule delete -g "$RG" -s "$SERVER" -n "$RULE" -o none' EXIT

export DB_SERVER="$SERVER_FQDN" DB_NAME="$DB" AZURE_MANAGED_IDENTITY_CLIENT_ID=""
echo "[2/4] Migraciones (la base puede tardar un minuto en reanudarse)"
(cd "$ROOT/backend" && "$PY" -m alembic upgrade head)

echo "[3/4] Usuario de la identidad del API: $IDENTITY"
(cd "$ROOT/backend" && IDENTITY="$IDENTITY" "$PY" - <<'PY'
import os
from sqlalchemy import text
from app.db import engine as db

nombre = os.environ["IDENTITY"].replace("]", "]]")
with db.connect() as c:
    c.execute(text(
        f"IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'{nombre}') "
        f"CREATE USER [{nombre}] FROM EXTERNAL PROVIDER"
    ))
    for rol in ("db_datareader", "db_datawriter", "db_ddladmin"):
        c.execute(text(f"ALTER ROLE {rol} ADD MEMBER [{nombre}]"))
    c.commit()
    roles = c.execute(text(
        "SELECT r.name FROM sys.database_role_members m "
        "JOIN sys.database_principals r ON r.principal_id = m.role_principal_id "
        "JOIN sys.database_principals u ON u.principal_id = m.member_principal_id "
        "WHERE u.name = :n ORDER BY r.name"), {"n": os.environ["IDENTITY"]}).scalars().all()
    print("  roles:", ", ".join(roles))
PY
)

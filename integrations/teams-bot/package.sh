#!/usr/bin/env bash
# Genera manifest.zip para cargar la app en Microsoft Teams.
#
# Uso:
#   BOT_APP_ID=<app id del bot> BACKEND_HOST=<app>.azurewebsites.net \
#   DEVELOPER_NAME="Tu nombre" DEVELOPER_URL=https://tu-sitio.dev ./package.sh
set -euo pipefail
cd "$(dirname "$0")"

: "${BOT_APP_ID:?Define BOT_APP_ID (Application ID del registro del bot)}"
: "${BACKEND_HOST:?Define BACKEND_HOST (host publico del backend, sin https://)}"
export DEVELOPER_NAME="${DEVELOPER_NAME:-CloudOps Copilot}"
export DEVELOPER_URL="${DEVELOPER_URL:-https://github.com/miguelortiz13/cloudops-copilot}"
export BOT_APP_ID BACKEND_HOST

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
envsubst < manifest.template.json > "$tmp/manifest.json"
cp color.png outline.png "$tmp/"
(cd "$tmp" && zip -q manifest.zip manifest.json color.png outline.png)
mv "$tmp/manifest.zip" .
echo "manifest.zip generado para el bot $BOT_APP_ID"

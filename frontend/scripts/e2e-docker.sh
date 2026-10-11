#!/usr/bin/env bash
# Corre las pruebas E2E (incluida la regresión visual) dentro de la imagen
# oficial de Playwright, la misma que usa la CI: las capturas solo son
# comparables si se renderizan con las mismas fuentes y el mismo Chromium.
#
#   ./scripts/e2e-docker.sh                       # todas
#   ./scripts/e2e-docker.sh --update-snapshots    # regenera las capturas
#   ./scripts/e2e-docker.sh e2e/visual.spec.ts    # un archivo
#
# node_modules va en un volumen propio del contenedor: no toca el del equipo.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(node -p "require('./node_modules/@playwright/test/package.json').version")
IMAGEN="mcr.microsoft.com/playwright:v${VERSION}-noble"

# Corre como root (el volumen de node_modules es de root) y al terminar
# devuelve lo generado (build, resultados, capturas) al usuario del equipo.
docker run --rm --ipc=host \
  -e CI=1 -e DUENO="$(id -u):$(id -g)" \
  -v "$PWD":/work -v /work/node_modules -w /work \
  "$IMAGEN" \
  bash -c 'npm ci --no-audit --no-fund --loglevel=error && npx playwright test "$@"; estado=$?
           chown -R "$DUENO" dist-e2e test-results playwright-report e2e/__screenshots__ 2>/dev/null
           exit $estado' _ "$@"

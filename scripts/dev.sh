#!/usr/bin/env bash
# Levanta backend (FastAPI :8000) y frontend (Vite :5173) en modo desarrollo.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
trap 'echo; echo "Deteniendo servidores..."; kill 0' EXIT

PY="python3"
[ -x "$ROOT/backend/.venv/bin/python" ] && PY="$ROOT/backend/.venv/bin/python"

echo "Backend  -> http://localhost:8000 (docs en /docs)"
(cd "$ROOT/backend" && "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload) &

[ -d "$ROOT/frontend/node_modules" ] || npm install --prefix "$ROOT/frontend"
echo "Frontend -> http://localhost:5173"
npm run dev --prefix "$ROOT/frontend" &

wait

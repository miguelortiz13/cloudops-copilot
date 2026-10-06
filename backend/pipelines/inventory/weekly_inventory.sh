#!/usr/bin/env bash
# weekly_inventory.sh — Orquestador semanal del inventario Azure
set -euo pipefail

BASE="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$BASE/scripts"
# Los datos viven en DATA_DIR (el mismo directorio persistente del API).
DATA_DIR="${DATA_DIR:-$BASE/../../data}"
export DATA_DIR
LOG="$DATA_DIR/snapshots/weekly_$(date +%Y-%m-%d).log"
mkdir -p "$DATA_DIR/snapshots"

exec > >(tee -a "$LOG") 2>&1

echo "========================================"
echo " Inventario Azure — $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

step() { echo; echo "── $1"; }

step "0/8 Preparando el Excel maestro (solo si no existe)"
python3 "$SCRIPTS/bootstrap_workbook.py"

step "1/8 Exportando recursos desde Azure Graph (paginación completa)"
python3 "$SCRIPTS/export_all.py"

step "2/8 Actualizando hojas de resumen del Excel (sin tocar master)"
python3 "$SCRIPTS/update_excel.py"

step "3/8 Sincronizando recursos existentes (tags, resourceGroup, location)"
python3 "$SCRIPTS/sync_master.py"

step "4/8 Agregando recursos nuevos al master"
python3 "$SCRIPTS/enrich_master.py"

step "5/8 Normalizando adoption_priority, candidate_module, requires_terraform_import"
python3 "$SCRIPTS/finalize_master.py"

step "6/8 Enriqueciendo desde tags (owner, environment, evidence_source, known_drift)"
python3 "$SCRIPTS/tags_enrich.py"
python3 "$SCRIPTS/fix_owner_pm.py"
python3 "$SCRIPTS/normalize_classify.py"

step "7/8 Clasificando método de provisión e inferencia"
python3 "$SCRIPTS/provisioning_classify.py"
python3 "$SCRIPTS/classify_assets_iso.py"

step "8/8 Generando snapshot versionado y hoja de trazabilidad"
python3 "$SCRIPTS/weekly_snapshot.py"

echo
echo "========================================"
echo " ✅ Completado — $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

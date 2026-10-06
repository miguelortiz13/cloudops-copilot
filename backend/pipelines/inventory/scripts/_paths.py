"""
Rutas compartidas por los scripts del pipeline de inventario.

Los datos (exportaciones, Excel maestro, snapshots) viven en DATA_DIR, el mismo
directorio persistente que usa el API; el codigo del pipeline no guarda nada en
su propia carpeta. Sin DATA_DIR se usa backend/data.
"""

import os
from pathlib import Path

PIPELINE = Path(__file__).resolve().parent.parent
BACKEND = PIPELINE.parent.parent
DATA = Path(os.getenv("DATA_DIR") or os.getenv("EXCEL_STORAGE_DIR") or BACKEND / "data")

QUERIES = PIPELINE / "queries"
RAW = DATA / "raw"
EXPORTS = DATA / "exports"
SNAPSHOTS = DATA / "snapshots"
EXCEL = DATA / "Azure_IaC_Inventario.xlsx"

for _d in (RAW, EXPORTS, SNAPSHOTS):
    _d.mkdir(parents=True, exist_ok=True)

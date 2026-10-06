#!/usr/bin/env python3
# update_excel.py — Actualiza el Excel con los CSVs exportados.
# La hoja 09_analysis_master NO se modifica.
import csv, json
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from _paths import EXCEL, EXPORTS, SNAPSHOTS  # noqa: F401
PROTECTED = "09_analysis_master"

# Mapa: nombre_hoja → archivo CSV (columnas reales en fila 1)
SHEET_MAP = {
    "00_subscriptions":         "subscriptions.csv",
    "01_inventory_raw":         "resources_full.csv",
    "02_type_summary":          "summary_by_type.csv",
    "03_summary_by_subscription": "summary_by_subscription.csv",
    "04_summary_by_rg":         "summary_by_rg.csv",
    "05_summary_by_location":   "summary_by_location.csv",
    "06_resources_with_tags":   "resources_with_tags.csv",
    "07_missing_owner":         "missing_owner.csv",
    "08_missing_environment":   "missing_environment.csv",
}

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(bold=True, color="FFFFFF")


def load_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return (reader.fieldnames or []), rows


def write_sheet(ws, headers: list[str], rows: list[dict]):
    ws.delete_rows(1, ws.max_row)

    # Header
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

    # Data
    for r_idx, row in enumerate(rows, 2):
        for c_idx, h in enumerate(headers, 1):
            ws.cell(row=r_idx, column=c_idx, value=row.get(h, ""))

    # Auto-width (capped at 60)
    for col in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col), default=0)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 2, 60)


def main():
    wb = openpyxl.load_workbook(EXCEL)

    for sheet_name, csv_file in SHEET_MAP.items():
        csv_path = EXPORTS / csv_file
        if not csv_path.exists():
            print(f"  ⚠ CSV no encontrado, omitiendo: {csv_path.name}")
            continue

        headers, rows = load_csv(csv_path)
        if sheet_name not in wb.sheetnames:
            wb.create_sheet(sheet_name)
            print(f"  + Hoja creada: {sheet_name}")

        ws = wb[sheet_name]
        write_sheet(ws, headers, rows)
        print(f"  ✓ {sheet_name}: {len(rows)} filas ({csv_file})")

    # Verificar que la hoja protegida no fue tocada
    assert PROTECTED in wb.sheetnames, f"¡Hoja {PROTECTED} no encontrada!"
    print(f"\n  🔒 {PROTECTED} intacta")

    wb.save(EXCEL)
    print(f"\n✅ Excel actualizado: {EXCEL.name}")


if __name__ == "__main__":
    main()

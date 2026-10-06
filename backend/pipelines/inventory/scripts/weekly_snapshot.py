#!/usr/bin/env python3
# weekly_snapshot.py — Genera copia versionada del Excel y hoja de trazabilidad con diff.
import shutil, openpyxl
from datetime import date
from pathlib import Path
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from _paths import EXCEL, EXPORTS, SNAPSHOTS  # noqa: F401
SHEET_MASTER = "09_analysis_master"
SHEET_DIFF   = "10_trazabilidad"
TODAY        = date.today().isoformat()

FILL_NEW  = PatternFill("solid", fgColor="C6EFCE")   # verde
FILL_DEL  = PatternFill("solid", fgColor="FFC7CE")   # rojo
FILL_HEAD = PatternFill("solid", fgColor="1F4E79")
FONT_HEAD = Font(bold=True, color="FFFFFF")
FONT_NEW  = Font(bold=True, color="375623")
FONT_DEL  = Font(bold=True, color="9C0006")


def load_master_ids(wb) -> dict[str, tuple]:
    """Retorna {resource_id: (name, type, resourceGroup, subscriptionId/name)} del master."""
    ws = wb[SHEET_MASTER]
    headers = [c.value for c in ws[1]]
    col = {h: i for i, h in enumerate(headers) if h}
    result = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        rid = row[col.get("resource_id", -1)] if col.get("resource_id") is not None else None
        if rid:
            sub_name = row[col.get("subscription_name", col["subscriptionId"])]
            result[rid] = (
                row[col["name"]],
                row[col["type"]],
                row[col.get("resourceGroup", col.get("resourcegroup", 0))],
                sub_name if sub_name else row[col["subscriptionId"]],
            )
    return result


def find_previous_snapshot() -> Path | None:
    """Encuentra el snapshot más reciente anterior a hoy."""
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    snaps = sorted(SNAPSHOTS.glob("Azure_IaC_Inventario_*.xlsx"), reverse=True)
    return snaps[0] if snaps else None


def write_diff_sheet(wb, added: list, removed: list):
    """Escribe de forma acumulativa en la hoja 10_trazabilidad con el diff de hoy."""
    existing_rows = []
    headers = ["fecha", "cambio", "resource_id", "name", "type", "resourceGroup", "subscription"]

    if SHEET_DIFF in wb.sheetnames:
        ws = wb[SHEET_DIFF]
        # Leer filas existentes, conservando únicamente históricos de tipo ELIMINADO
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row and len(row) >= 2 and row[0] != TODAY:
                cambio = str(row[1]).upper()
                if cambio == "ELIMINADO":
                    existing_rows.append(row)
        del wb[SHEET_DIFF]

    ws = wb.create_sheet(SHEET_DIFF)

    # Escribir cabecera
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.fill = FILL_HEAD
        cell.font = FONT_HEAD
        cell.alignment = Alignment(horizontal="center")

    row_idx = 2

    # Escribir filas históricas conservadas
    for row_data in existing_rows:
        cambio = row_data[1] if len(row_data) > 1 else ""
        fill = FILL_NEW if cambio == "NUEVO" else (FILL_DEL if cambio == "ELIMINADO" else None)
        font = FONT_NEW if cambio == "NUEVO" else (FONT_DEL if cambio == "ELIMINADO" else None)

        for c, v in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=c, value=v)
            if fill: cell.fill = fill
            if font: cell.font = font
        row_idx += 1

    # Escribir nuevos cambios de hoy
    for rid, info in added:
        data = [TODAY, "NUEVO", rid] + list(info)
        for c, v in enumerate(data, 1):
            cell = ws.cell(row=row_idx, column=c, value=v)
            cell.fill = FILL_NEW
            cell.font = FONT_NEW
        row_idx += 1

    for rid, info in removed:
        data = [TODAY, "ELIMINADO", rid] + list(info)
        for c, v in enumerate(data, 1):
            cell = ws.cell(row=row_idx, column=c, value=v)
            cell.fill = FILL_DEL
            cell.font = FONT_DEL
        row_idx += 1

    # Auto-width
    for col in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col), default=0)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 2, 60)

    return len(added), len(removed)


def main():
    wb_current = openpyxl.load_workbook(EXCEL)
    if "Hoja1" in wb_current.sheetnames:
        del wb_current["Hoja1"]
    current_ids = load_master_ids(wb_current)

    prev_path = find_previous_snapshot()
    if prev_path:
        wb_prev = openpyxl.load_workbook(prev_path, read_only=True, data_only=True)
        prev_ids = load_master_ids(wb_prev) if SHEET_MASTER in wb_prev.sheetnames else {}
        print(f"  Comparando con snapshot: {prev_path.name}")
    else:
        prev_ids = {}
        print("  Sin snapshot previo — primera ejecución, sin diff.")

    added   = [(rid, info) for rid, info in current_ids.items() if rid not in prev_ids]
    removed = [(rid, info) for rid, info in prev_ids.items()    if rid not in current_ids]

    n_add, n_del = write_diff_sheet(wb_current, added, removed)
    print(f"  Nuevos:     {n_add}")
    print(f"  Eliminados: {n_del}")

    wb_current.save(EXCEL)

    # Generar copia versionada
    version_name = f"Azure_IaC_Inventario_{TODAY}.xlsx"
    dest = SNAPSHOTS / version_name
    shutil.copy2(EXCEL, dest)
    print(f"  Snapshot guardado: snapshots/{version_name}")


if __name__ == "__main__":
    main()

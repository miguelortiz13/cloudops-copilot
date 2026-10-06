#!/usr/bin/env python3
# normalize_classify.py — Normaliza environment, rellena known_drift y genera matriz de priorización
import openpyxl
from collections import defaultdict
from pathlib import Path
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from _paths import EXCEL, EXPORTS, SNAPSHOTS  # noqa: F401
SHEET = "09_analysis_master"

# ── Normalización de environment ──────────────────────────────────────────
ENV_MAP = {
    "prod": "Prod", "production": "Prod", "prd": "Prod", "produccion": "Prod",
    "dev": "Dev", "development": "Dev", "desarrollo": "Dev",
    "qa": "QA", "test": "QA", "testing": "QA", "uat": "QA",
    "devqa": "DevQA", "dev/qa": "DevQA", "dev-qa": "DevQA",
    "stage": "Stage", "staging": "Stage",
    "inactivo": "Inactivo", "inactive": "Inactivo",
    "migration": "Migration", "migración": "Migration",
    "validation": "Validation",
}

def normalize_env(val: str) -> str:
    return ENV_MAP.get(val.lower().strip(), val.strip()) if val else ""

# ── Regla known_drift ─────────────────────────────────────────────────────
def infer_drift(pm: str) -> str:
    pm = (pm or "").lower()
    if pm == "terraform":  return "No"
    if pm == "devops":     return "Revisar"
    return "Desconocido"

# ── Estilos para la matriz ────────────────────────────────────────────────
FILL_HEADER  = PatternFill("solid", fgColor="1F4E79")
FILL_DOMAIN  = PatternFill("solid", fgColor="2E75B6")
FILL_ALTA    = PatternFill("solid", fgColor="C6EFCE")
FILL_MEDIA   = PatternFill("solid", fgColor="FFEB9C")
FILL_BAJA    = PatternFill("solid", fgColor="FFCCCC")
FILL_EMPTY   = PatternFill("solid", fgColor="F2F2F2")
FONT_WHITE   = Font(bold=True, color="FFFFFF")
FONT_BOLD    = Font(bold=True)
THIN         = Side(style="thin", color="BFBFBF")
BORDER       = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER       = Alignment(horizontal="center", vertical="center")


def main():
    wb = openpyxl.load_workbook(EXCEL)
    ws = wb[SHEET]
    headers = [c.value for c in ws[1]]
    col = {h: i+1 for i, h in enumerate(headers) if h}

    env_fixed = 0
    drift_filled = 0

    # ── Paso 1: normalizar environment + rellenar known_drift ─────────────
    for row in ws.iter_rows(min_row=2):
        # environment
        cell_env = row[col["environment"]-1]
        norm = normalize_env(str(cell_env.value or ""))
        if norm and norm != cell_env.value:
            cell_env.value = norm
            env_fixed += 1

        # known_drift — solo si vacío
        cell_drift = row[col["known_drift"]-1]
        if not cell_drift.value:
            pm = row[col["provisioning_method"]-1].value
            cell_drift.value = infer_drift(pm)
            drift_filled += 1

    print(f"  environment normalizado:  {env_fixed}")
    print(f"  known_drift rellenado:    {drift_filled}")

    # ── Paso 2: recopilar datos para la matriz ────────────────────────────
    # estructura: {domain: {env: {Alta:n, Media:n, Baja:n, total:n}}}
    DOMAINS = ["platform","data","networking","security","observability","integration","devcenter"]
    ENVS_ORDER = ["Prod","QA","Dev","DevQA","Stage","Validation","Migration","Inactivo",""]

    matrix: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"Alta":0,"Media":0,"Baja":0,"total":0}))
    env_set: set[str] = set()

    for row in ws.iter_rows(min_row=2, values_only=True):
        d  = row[col["domain"]-1] or ""
        e  = row[col["environment"]-1] or ""
        ap = row[col["adoption_priority"]-1] or ""
        if d in DOMAINS:
            matrix[d][e]["total"] += 1
            if ap in ("Alta","Media","Baja"):
                matrix[d][e][ap] += 1
            env_set.add(e)

    # Ordenar ambientes: primero los conocidos, luego el resto
    envs = [e for e in ENVS_ORDER if e in env_set] + sorted(env_set - set(ENVS_ORDER))

    # ── Paso 3: escribir hoja de matriz ───────────────────────────────────
    SHEET_MATRIX = "11_matriz_priorizacion"
    if SHEET_MATRIX in wb.sheetnames:
        del wb[SHEET_MATRIX]
    wm = wb.create_sheet(SHEET_MATRIX)

    # Título
    wm.merge_cells("A1:B1")
    wm["A1"] = "Dominio / Ambiente"
    wm["A1"].fill = FILL_HEADER
    wm["A1"].font = FONT_WHITE
    wm["A1"].alignment = CENTER
    wm["A1"].border = BORDER

    # Headers de ambiente (cada ambiente ocupa 2 cols: total | Alta/Media/Baja)
    col_start = 3
    env_col: dict[str, int] = {}
    for env in envs:
        label = env if env else "(sin env)"
        wm.merge_cells(start_row=1, start_column=col_start, end_row=1, end_column=col_start+1)
        cell = wm.cell(row=1, column=col_start, value=label)
        cell.fill = FILL_HEADER
        cell.font = FONT_WHITE
        cell.alignment = CENTER
        cell.border = BORDER
        env_col[env] = col_start
        col_start += 2

    # Sub-headers fila 2
    wm.cell(row=2, column=1, value="Dominio").fill = FILL_DOMAIN
    wm.cell(row=2, column=1).font = FONT_WHITE
    wm.cell(row=2, column=1).border = BORDER
    wm.cell(row=2, column=2, value="Total").fill = FILL_DOMAIN
    wm.cell(row=2, column=2).font = FONT_WHITE
    wm.cell(row=2, column=2).border = BORDER
    for env in envs:
        c = env_col[env]
        for offset, label in enumerate(["Total", "Alta/Media/Baja"]):
            cell = wm.cell(row=2, column=c+offset, value=label)
            cell.fill = FILL_DOMAIN
            cell.font = FONT_WHITE
            cell.alignment = CENTER
            cell.border = BORDER

    # Filas por dominio
    for r_idx, domain in enumerate(DOMAINS, 3):
        domain_total = sum(matrix[domain][e]["total"] for e in envs)

        wm.cell(row=r_idx, column=1, value=domain).font = FONT_BOLD
        wm.cell(row=r_idx, column=1).border = BORDER
        wm.cell(row=r_idx, column=2, value=domain_total).font = FONT_BOLD
        wm.cell(row=r_idx, column=2).alignment = CENTER
        wm.cell(row=r_idx, column=2).border = BORDER

        for env in envs:
            c = env_col[env]
            data = matrix[domain][env]
            total_env = data["total"]
            alta, media, baja = data["Alta"], data["Media"], data["Baja"]

            # Total
            cell_t = wm.cell(row=r_idx, column=c, value=total_env if total_env else "")
            cell_t.alignment = CENTER
            cell_t.border = BORDER
            if not total_env:
                cell_t.fill = FILL_EMPTY

            # Desglose prioridad
            if total_env:
                desglose = f"A:{alta} M:{media} B:{baja}"
                fill = FILL_ALTA if alta >= media and alta >= baja else (FILL_MEDIA if media >= baja else FILL_BAJA)
            else:
                desglose = ""
                fill = FILL_EMPTY
            cell_d = wm.cell(row=r_idx, column=c+1, value=desglose)
            cell_d.fill = fill
            cell_d.alignment = CENTER
            cell_d.border = BORDER

    # Fila TOTAL
    total_row = len(DOMAINS) + 3
    wm.cell(row=total_row, column=1, value="TOTAL").font = Font(bold=True, color="FFFFFF")
    wm.cell(row=total_row, column=1).fill = FILL_HEADER
    wm.cell(row=total_row, column=1).border = BORDER
    grand_total = sum(sum(matrix[d][e]["total"] for e in envs) for d in DOMAINS)
    wm.cell(row=total_row, column=2, value=grand_total).font = Font(bold=True)
    wm.cell(row=total_row, column=2).alignment = CENTER
    wm.cell(row=total_row, column=2).border = BORDER
    for env in envs:
        c = env_col[env]
        env_total = sum(matrix[d][env]["total"] for d in DOMAINS)
        cell = wm.cell(row=total_row, column=c, value=env_total if env_total else "")
        cell.fill = FILL_HEADER
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = CENTER
        cell.border = BORDER
        wm.cell(row=total_row, column=c+1).fill = FILL_HEADER
        wm.cell(row=total_row, column=c+1).border = BORDER

    # Auto-width
    for c in range(1, col_start):
        wm.column_dimensions[get_column_letter(c)].width = 14

    wm.column_dimensions["A"].width = 18
    wm.freeze_panes = "C3"

    wb.save(EXCEL)
    print(f"  Hoja '{SHEET_MATRIX}' generada")

    # Retornar datos para el wiki
    return matrix, envs, DOMAINS


if __name__ == "__main__":
    main()

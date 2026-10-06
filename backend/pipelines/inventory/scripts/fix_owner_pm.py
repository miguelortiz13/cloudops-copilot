#!/usr/bin/env python3
# fix_owner_pm.py — Mueve emails/nombres de provisioning_method → owner_confirmed
# y resetea provisioning_method a "unknown" en esos casos.
import ast, openpyxl
from pathlib import Path

from _paths import EXCEL, EXPORTS, SNAPSHOTS  # noqa: F401
SHEET = "09_analysis_master"

OWNER_KEYS = ["owner", "ownertech", "ownerfunc", "createdby", "managedby", "author", "autor"]
VALID_PM   = {"terraform", "portal", "unknown", "arm", "bicep", "cli", "sdk", "devops"}

def parse_tags(raw) -> dict:
    if not raw: return {}
    try:
        t = ast.literal_eval(str(raw)) if isinstance(raw, str) else raw
        return {k.lower().strip(): v for k, v in t.items()} if isinstance(t, dict) else {}
    except:
        return {}

def is_owner_value(val: str) -> bool:
    """True si el valor parece un email o nombre de persona, no un método."""
    v = val.lower().strip()
    return "@" in v or (v not in VALID_PM and len(v) > 2)

def main():
    wb = openpyxl.load_workbook(EXCEL)
    ws = wb[SHEET]
    headers = [c.value for c in ws[1]]
    col = {h: i+1 for i, h in enumerate(headers) if h}

    moved = 0
    owner_filled = 0

    for row in ws.iter_rows(min_row=2):
        tags = parse_tags(row[col["tags"]-1].value)
        pm_cell    = row[col["provisioning_method"]-1]
        owner_cell = row[col["owner_confirmed"]-1]
        pm_val = str(pm_cell.value or "").strip()

        # Si provisioning_method tiene un email/nombre → moverlo a owner_confirmed
        if pm_val and is_owner_value(pm_val):
            # Solo escribir owner si está vacío o "Por confirmar"
            if not owner_cell.value or str(owner_cell.value).lower() in ("por confirmar", ""):
                owner_cell.value = pm_val
                owner_filled += 1
            pm_cell.value = "unknown"
            moved += 1

        # Segunda pasada: rellenar owner_confirmed desde tags createdby/managedby si aún vacío
        if not owner_cell.value or str(owner_cell.value).lower() == "por confirmar":
            for k in OWNER_KEYS:
                v = tags.get(k, "")
                if v and str(v).strip():
                    owner_cell.value = str(v).strip()
                    owner_filled += 1
                    break

    wb.save(EXCEL)
    print(f"  provisioning_method corregidos: {moved}")
    print(f"  owner_confirmed actualizados:   {owner_filled}")
    print(f"\n✅ {EXCEL.name} guardado")

if __name__ == "__main__":
    main()

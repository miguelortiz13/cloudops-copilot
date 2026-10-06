#!/usr/bin/env python3
# tags_enrich.py — Rellena campos vacíos en 09_analysis_master usando los tags del recurso.
# Solo escribe si el campo está vacío o es "Por confirmar" / "sin evidencia aún" / "unknown".
import ast, openpyxl
from pathlib import Path

from _paths import EXCEL, EXPORTS, SNAPSHOTS  # noqa: F401
SHEET = "09_analysis_master"

# Tag keys candidatas para cada campo (en orden de preferencia)
OWNER_KEYS   = ["owner", "ownertech", "ownerfunc", "createdby", "managedby", "author", "autor"]
ENV_KEYS     = ["environment", "entorno", "enviroment"]

EMPTY_VALUES = {"", None, "por confirmar", "sin evidencia aún", "unknown"}

def parse_tags(raw) -> dict:
    if not raw:
        return {}
    try:
        t = ast.literal_eval(str(raw)) if isinstance(raw, str) else raw
        return {k.lower().strip(): v for k, v in t.items()} if isinstance(t, dict) else {}
    except:
        return {}

def first_tag(tags: dict, keys: list[str]) -> str | None:
    for k in keys:
        v = tags.get(k)
        if v and str(v).strip():
            return str(v).strip()
    return None

def is_empty(val) -> bool:
    return str(val).lower().strip() in EMPTY_VALUES if val is not None else True

def main():
    wb = openpyxl.load_workbook(EXCEL)
    ws = wb[SHEET]

    headers = [c.value for c in ws[1]]
    col = {h: i+1 for i, h in enumerate(headers) if h}

    counts = {"owner_confirmed": 0, "environment": 0,
              "provisioning_method": 0, "evidence_source": 0, "known_drift": 0}

    for row in ws.iter_rows(min_row=2):
        tags = parse_tags(row[col["tags"]-1].value)
        if not tags:
            continue

        # owner_confirmed
        cell = row[col["owner_confirmed"]-1]
        if is_empty(cell.value):
            val = first_tag(tags, OWNER_KEYS)
            if val:
                cell.value = val
                counts["owner_confirmed"] += 1

        # environment
        cell = row[col["environment"]-1]
        if is_empty(cell.value):
            val = first_tag(tags, ENV_KEYS)
            if val:
                cell.value = val
                counts["environment"] += 1

        # provisioning_method — si tiene tag 'createdby' o 'managedby' → terraform/portal/unknown
        cell = row[col["provisioning_method"]-1]
        if is_empty(cell.value):
            cb = tags.get("createdby", "").lower()
            mb = tags.get("managedby", "").lower()
            hint = cb or mb
            if "terraform" in hint:
                cell.value = "terraform"
            elif "portal" in hint or "azure" in hint:
                cell.value = "portal"
            elif hint:
                cell.value = hint
            if not is_empty(cell.value):
                counts["provisioning_method"] += 1

        # evidence_source — si tiene tags relevantes, hay evidencia mínima
        cell = row[col["evidence_source"]-1]
        if is_empty(cell.value) and tags:
            cell.value = "tags"
            counts["evidence_source"] += 1

        # known_drift — si provisioning_method es terraform y tiene tags → sin drift conocido
        cell = row[col["known_drift"]-1]
        if is_empty(cell.value):
            pm = row[col["provisioning_method"]-1].value or ""
            if str(pm).lower() == "terraform":
                cell.value = "No"
                counts["known_drift"] += 1

    wb.save(EXCEL)

    for field, n in counts.items():
        print(f"  {field}: {n} actualizados")
    print(f"\n✅ {EXCEL.name} guardado")

if __name__ == "__main__":
    main()

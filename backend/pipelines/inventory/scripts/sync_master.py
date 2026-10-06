#!/usr/bin/env python3
# sync_master.py — Sincroniza campos mutables del master con el export fresco de Azure.
# Mantiene SOLO recursos activos en 09_analysis_master.
# Guarda recursos eliminados en 13_historical_backup.
import ast, csv, openpyxl
from datetime import date
from pathlib import Path

from _paths import EXCEL, EXPORTS, SNAPSHOTS  # noqa: F401
SHEET   = "09_analysis_master"
TODAY   = date.today().isoformat()

SUBS: dict[str, str] = {}
with open(EXPORTS / "subscriptions.csv", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        SUBS[r["id"]] = r["name"]

# Campos que se sincronizan desde Azure
SYNC_FIELDS = {"tags", "resourceGroup", "location"}

def parse_tags(raw) -> dict:
    if not raw: return {}
    try:
        t = ast.literal_eval(str(raw)) if isinstance(raw, str) else raw
        return {k.lower().strip(): str(v).strip() for k,v in t.items()} if isinstance(t, dict) else {}
    except: return {}

def main():
    # Cargar export fresco indexado por resource_id
    fresh: dict[str, dict] = {}
    with open(EXPORTS / "resources_full.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            fresh[r["id"]] = r

    wb = openpyxl.load_workbook(EXCEL)
    
    # Eliminar Hoja1 si existe
    if "Hoja1" in wb.sheetnames:
        del wb["Hoja1"]
        print("  ✓ Hoja1 eliminada.")

    ws = wb[SHEET]
    headers = [c.value for c in ws[1]]
    col = {h: i+1 for i, h in enumerate(headers) if h}

    updated_tags = 0
    updated_rg   = 0
    updated_loc  = 0
    new_added    = 0
    existing_ids: set[str] = set()

    active_rows = []
    deleted_rows = []

    for r_idx in range(2, ws.max_row + 1):
        row_cells = [ws.cell(row=r_idx, column=c) for c in range(1, len(headers) + 1)]
        row_vals = [c.value for c in row_cells]
        
        # Saltar si fila vacía
        if not row_vals or not any(row_vals):
            continue

        rid = row_vals[col.get("resource_id", 0)-1] if "resource_id" in col else None

        # Evitar duplicados en el maestro
        if rid and rid in existing_ids:
            continue

        # Buscar en fresh
        fr = fresh.get(rid) if rid else None
        if not fr:
            # Intentar encontrar por name+type+sub
            name = row_vals[col["name"]-1]
            rtype = (row_vals[col["type"]-1] or "").lower()
            sub = row_vals[col["subscriptionId"]-1]
            rg = row_vals[col["resourceGroup"]-1]
            loc = row_vals[col["location"]-1]
            for fid, frow in fresh.items():
                if (frow.get("name") == name and
                    frow.get("type","").lower() == rtype and
                    frow.get("subscriptionId") == sub and
                    (not rg or str(frow.get("resourceGroup")).lower() == str(rg).lower()) and
                    (not loc or str(frow.get("location")).lower() == str(loc).lower())):
                    fr = frow
                    rid = fid
                    if "resource_id" in col:
                        row_cells[col["resource_id"]-1].value = rid
                        row_vals[col["resource_id"]-1] = rid
                    break

        if not fr:
            # Recurso eliminado: lo guardamos para el backup histórico
            deleted_rows.append(row_vals)
            continue

        # Recurso activo: lo procesamos y conservamos
        existing_ids.add(rid)

        # Sincronizar tags
        old_tags = row_vals[col["tags"]-1]
        new_tags = fr.get("tags", "")
        if str(old_tags) != str(new_tags):
            row_cells[col["tags"]-1].value = new_tags
            row_vals[col["tags"]-1] = new_tags
            updated_tags += 1

            tags_dict = parse_tags(new_tags)
            for owner_key in ["owner","ownertech","ownerfunc","createdby","managedby","author"]:
                v = tags_dict.get(owner_key, "")
                if v and "@" not in v and v.lower() not in ("por confirmar",""):
                    cell_o = row_cells[col["owner_confirmed"]-1]
                    if not cell_o.value or str(cell_o.value).lower() == "por confirmar":
                        cell_o.value = v
                        row_vals[col["owner_confirmed"]-1] = v
                    break
                elif v and "@" in v:
                    cell_o = row_cells[col["owner_confirmed"]-1]
                    if not cell_o.value or str(cell_o.value).lower() == "por confirmar":
                        cell_o.value = v
                        row_vals[col["owner_confirmed"]-1] = v
                    break

            for env_key in ["environment","entorno","enviroment"]:
                v = tags_dict.get(env_key, "")
                if v:
                    cell_e = row_cells[col["environment"]-1]
                    if not cell_e.value:
                        cell_e.value = v
                        row_vals[col["environment"]-1] = v
                    break

        # Sincronizar resourceGroup
        new_rg = fr.get("resourceGroup", "")
        if row_vals[col["resourceGroup"]-1] != new_rg:
            row_cells[col["resourceGroup"]-1].value = new_rg
            row_vals[col["resourceGroup"]-1] = new_rg
            updated_rg += 1

        # Sincronizar location
        new_loc = fr.get("location", "")
        if row_vals[col["location"]-1] != new_loc:
            row_cells[col["location"]-1].value = new_loc
            row_vals[col["location"]-1] = new_loc
            updated_loc += 1

        # Sincronizar subscription_name si vacío
        if "subscription_name" in col:
            sub_id = row_vals[col["subscriptionId"]-1]
            if not row_vals[col["subscription_name"]-1] and sub_id:
                row_cells[col["subscription_name"]-1].value = SUBS.get(sub_id, sub_id)
                row_vals[col["subscription_name"]-1] = SUBS.get(sub_id, sub_id)

        # Actualizar extraction_date
        if "extraction_date" in col:
            row_cells[col["extraction_date"]-1].value = TODAY
            row_vals[col["extraction_date"]-1] = TODAY

        active_rows.append(row_vals)

    # Re-escribir la hoja master con únicamente los recursos activos
    ws.delete_rows(2, ws.max_row)
    for r_vals in active_rows:
        ws.append(r_vals)

    # Guardar eliminados en el backup histórico
    if deleted_rows:
        SHEET_BACKUP = "13_historical_backup"
        if SHEET_BACKUP not in wb.sheetnames:
            ws_bk = wb.create_sheet(SHEET_BACKUP)
            ws_bk.views.sheetView[0].showGridLines = True
            for c_idx, h in enumerate(headers, 1):
                ws_bk.cell(row=1, column=c_idx, value=h)
        else:
            ws_bk = wb[SHEET_BACKUP]
        for r_vals in deleted_rows:
            ws_bk.append(r_vals)
        print(f"  ✓ {len(deleted_rows)} recursos eliminados movidos a {SHEET_BACKUP}.")

    # Agregar recursos nuevos
    from enrich_master import DOMAIN_MAP
    from finalize_master import TYPE_MAP

    for rid, fr in fresh.items():
        if rid in existing_ids:
            continue
        rtype = fr.get("type", "")
        sub   = fr.get("subscriptionId", "")
        d, sd = DOMAIN_MAP.get(rtype.lower(), ("", ""))
        module, priority, tf_import = TYPE_MAP.get(rtype.lower(), ("", "Media", "Si"))

        new_row = [None] * len(headers)
        def s(field, val):
            if field in col: new_row[col[field]-1] = val

        s("name",                    fr.get("name",""))
        s("type",                    rtype)
        s("resourceGroup",           fr.get("resourceGroup",""))
        s("subscriptionId",          sub)
        s("subscription_name",       SUBS.get(sub, sub))
        s("location",                fr.get("location",""))
        s("resource_id",             rid)
        s("domain",                  d)
        s("subdomain",               sd)
        s("environment",             "")
        s("owner_confirmed",         "Por confirmar")
        s("provisioning_method",     "unknown")
        s("adoption_priority",       priority)
        s("requires_terraform_import", tf_import)
        s("candidate_module",        module)
        s("evidence_source",         "tags" if fr.get("tags") else "sin evidencia aún")
        s("known_drift",             "Desconocido")
        s("tags",                    fr.get("tags",""))
        s("extraction_date",         TODAY)
        s("inventory_version",       "1.1")
        s("review_status",           "pendiente")

        ws.append(new_row)
        new_added += 1

    wb.save(EXCEL)

    print(f"  tags actualizados:        {updated_tags}")
    print(f"  resourceGroup movidos:    {updated_rg}")
    print(f"  location actualizados:    {updated_loc}")
    print(f"  recursos nuevos:          {new_added}")
    print(f"\n✅ {EXCEL.name} sincronizado")

if __name__ == "__main__":
    main()

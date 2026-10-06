#!/usr/bin/env python3
# provisioning_classify.py — Infiere provisioning_method con reglas y genera CSV de clasificación
import ast, csv, openpyxl
from pathlib import Path
from collections import Counter

from _paths import EXCEL, EXPORTS, SNAPSHOTS  # noqa: F401
OUT_CSV = EXPORTS / "provisioning-classification.csv"
SHEET   = "09_analysis_master"

# Tipos que Azure crea automáticamente (no son decisión del usuario)
AUTO_TYPES = {
    "microsoft.alertsmanagement/smartdetectoralertrules",
    "microsoft.compute/virtualmachines/extensions",
    "microsoft.automation/automationaccounts/runbooks",
    "microsoft.containerregistry/registries/webhooks",
    "microsoft.devtestlab/schedules",
    "microsoft.compute/restorepointcollections",
    "microsoft.compute/galleries/images/versions",
    "microsoft.network/privatednszones/virtualnetworklinks",
    "microsoft.operationsmanagement/solutions",
    "microsoft.insights/autoscalesettings",
    "microsoft.network/networkwatchers",
    "microsoft.insights/workbooks",
    "microsoft.portal/dashboards",
    "microsoft.resourcegraph/queries",
    "microsoft.saas/resources",
    "microsoft.migrate/movecollections",
    "microsoft.web/certificates",
    "microsoft.compute/sshpublickeys",
    "microsoft.compute/images",
    "microsoft.compute/snapshots",
}

def parse_tags(raw) -> dict:
    if not raw: return {}
    try:
        t = ast.literal_eval(str(raw)) if isinstance(raw, str) else raw
        return {k.lower().strip(): str(v).strip() for k,v in t.items()} if isinstance(t, dict) else {}
    except: return {}

def is_email(val: str) -> bool:
    return "@" in val and "." in val

def infer(rtype: str, tags: dict, current_pm: str) -> tuple[str, str]:
    """Returns (method, confidence): confirmado | inferido | desconocido"""
    rtype = rtype.lower()

    # Ya confirmado manualmente
    if current_pm in ("terraform", "portal", "bicep", "arm", "cli"):
        return current_pm, "confirmado"

    # Tag managedby
    mb = tags.get("managedby", "").lower()
    if "terraform" in mb: return "terraform", "confirmado"
    if "bicep" in mb:     return "bicep", "confirmado"
    if "arm" in mb:       return "arm", "confirmado"

    # Tag createdby
    cb = tags.get("createdby", "").lower()
    if "terraform" in cb: return "terraform", "confirmado"
    if "bicep" in cb:     return "bicep", "confirmado"
    if is_email(cb):      return "portal", "inferido"

    # Tag ftk-tool (Farmer Toolkit)
    if tags.get("ftk-tool"): return "terraform", "inferido"

    # Tipo auto-gestionado por Azure
    if rtype in AUTO_TYPES: return "auto", "inferido"

    # devops pipeline (current_pm ya lo tiene)
    if current_pm == "devops": return "devops", "confirmado"

    return "unknown", "desconocido"


def main():
    wb = openpyxl.load_workbook(EXCEL)
    ws = wb[SHEET]
    headers = [c.value for c in ws[1]]
    col = {h: i+1 for i, h in enumerate(headers) if h}

    rows_out = []
    pm_updated = 0
    confidence_counts = Counter()

    for row in ws.iter_rows(min_row=2):
        rtype   = str(row[col["type"]-1].value or "")
        tags    = parse_tags(row[col["tags"]-1].value)
        cur_pm  = str(row[col["provisioning_method"]-1].value or "")
        name    = row[col["name"]-1].value
        rg      = row[col["resourceGroup"]-1].value
        sub     = row[col["subscriptionId"]-1].value
        domain  = row[col["domain"]-1].value
        env     = row[col["environment"]-1].value
        rid     = row[col["resource_id"]-1].value if "resource_id" in col else ""

        method, confidence = infer(rtype, tags, cur_pm)
        confidence_counts[confidence] += 1

        # Actualizar en Excel solo si cambia y no era ya confirmado
        if method != cur_pm and confidence in ("confirmado", "inferido"):
            row[col["provisioning_method"]-1].value = method
            pm_updated += 1

        rows_out.append({
            "resource_id":          rid,
            "name":                 name,
            "type":                 rtype,
            "resourceGroup":        rg,
            "subscriptionId":       sub,
            "domain":               domain,
            "environment":          env,
            "provisioning_method":  method,
            "confidence":           confidence,
        })

    wb.save(EXCEL)

    # Escribir CSV
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)

    print(f"  provisioning_method actualizados en Excel: {pm_updated}")
    print(f"  Confianza:")
    for k, v in confidence_counts.most_common():
        print(f"    {v:4d}  {k}")
    print(f"\n  CSV generado: {OUT_CSV.name}")

    # Resumen por método
    print("\n  Distribución final:")
    for v, c in Counter(r["provisioning_method"] for r in rows_out).most_common():
        print(f"    {c:4d}  {v}")


if __name__ == "__main__":
    main()

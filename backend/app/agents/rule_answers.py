"""
Respuestas del motor de reglas para los agentes de costos y seguridad.

Sin clave de Gemini (o si el modelo falla), el agente respondia siempre con las
reglas de inventario, sin importar a que agente se le preguntara: el de costos
contestaba "no logre interpretar tu pregunta" a "en que se va el gasto". Aqui
cada agente responde con los mismos servicios que alimentan su pestaña, de modo
que el chat sin IA sigue siendo util y nunca contradice al panel.
"""

from typing import Any, Dict, List, Optional

from app.services.cost_overview_service import CostOverviewService

AHORRO = ("ahorr", "huerf", "huérf", "optimiz", "desperdic", "reduc", "sin uso", "apagar")


def _money(valor: Optional[float], moneda: str = "USD") -> str:
    if valor is None:
        return "—"
    return f"{valor:,.2f} {moneda}"


def _lista(titulo: str, filas: List[str]) -> str:
    if not filas:
        return ""
    return f"\n**{titulo}**\n" + "\n".join(f"- {f}" for f in filas) + "\n"


def respuesta_finops(agente, pregunta: str, subs: Optional[List[str]]) -> Dict[str, Any]:
    texto = pregunta.lower()
    costo = agente._get_cost()

    if any(p in texto for p in AHORRO) and getattr(agente, "_finops", None) is not None:
        reporte = agente._finops.build_report(subs or None)
        ciclo = reporte.get("savings_lifecycle") or {}
        moneda = (reporte.get("cost_data") or {}).get("currency", "USD")
        huerfanos = []
        for clave, etiqueta in (
            ("unattached_disks", "Disco sin VM"), ("unassociated_ips", "IP pública libre"),
            ("orphaned_nics", "NIC sin VM"), ("empty_app_plans", "Plan de App Service vacío"),
            ("old_snapshots", "Snapshot antiguo"),
        ):
            for r in reporte.get(clave) or []:
                huerfanos.append((r.get("monthly_cost_usd") or 0.0, f"`{r.get('name')}` · {etiqueta} · {_money(r.get('monthly_cost_usd'), moneda)}/mes"))
        huerfanos.sort(reverse=True)
        respuesta = (
            "### Oportunidades de ahorro\n"
            f"Ahorro potencial mensual: **{_money(ciclo.get('potential_savings_usd', 0.0), moneda)}**.\n"
            f"- Apagado programado de VMs de dev/QA: {_money(ciclo.get('schedule_savings_usd', 0.0), moneda)}\n"
            f"- Reservas y Savings Plans: {_money(ciclo.get('reservation_savings_usd', 0.0), moneda)}\n"
        )
        respuesta += _lista("Recursos sin uso", [h for _, h in huerfanos[:8]]) or "\nNo hay recursos sin uso detectados.\n"
        return {"answer": respuesta, "mode": "azure_live_rules_finops", "data": []}

    vista = CostOverviewService(agente, costo).build(subs or None)
    t = vista["totals"]
    moneda = vista["currency"]
    delta = t.get("delta_percentage")
    variacion = f" ({'+' if delta > 0 else ''}{delta:.1f} % frente a los 30 días anteriores)" if delta is not None else ""
    respuesta = (
        "### Gasto de los últimos 30 días\n"
        f"Total: **{_money(t['last_period'], moneda)}**{variacion}.\n"
        f"- Mes en curso: {_money(t.get('month_to_date'), moneda)} · proyección al cierre: {_money(t.get('forecast_month'), moneda)}\n"
        f"- Promedio diario: {_money(t['daily_average'], moneda)}\n"
    )
    respuesta += _lista("Por servicio", [f"{g['key']}: {_money(g['cost'], moneda)} ({g['share']} %)" for g in vista["by_service"][:5]])
    respuesta += _lista("Recursos más costosos", [
        f"`{r['name']}` ({r['service']}): {_money(r['cost'], moneda)} · {r['share']} %"
        + (" · eliminado" if r["deleted"] else "")
        for r in vista["top_resources"][:5]
    ])
    for tag, grupos in (vista.get("by_tag") or {}).items():
        respuesta += _lista(f"Por {tag}", [f"{g['key']}: {_money(g['cost'], moneda)} ({g['share']} %)" for g in grupos[:5]])
        break
    respuesta += f"\n_{vista['message']}_"
    return {"answer": respuesta, "mode": "azure_live_rules_finops", "data": []}


def respuesta_secops(agente, subs: Optional[List[str]]) -> Dict[str, Any]:
    riesgo = getattr(agente, "_risk", None)
    if riesgo is not None:
        reporte = riesgo.build_report(subs or [])
    else:
        reporte = agente._get_secops().build_report(subs or [])
    hallazgos = reporte.get("findings") or []
    conteo = {"critica": 0, "alta": 0, "media": 0}
    for h in hallazgos:
        conteo[h.get("severidad", "media")] = conteo.get(h.get("severidad", "media"), 0) + 1

    respuesta = (
        "### Postura de seguridad\n"
        f"- Críticos: **{conteo['critica']}** · Altos: **{conteo['alta']}** · Medios: **{conteo['media']}**\n"
    )
    if not hallazgos:
        return {"answer": respuesta + "\nNo hay hallazgos en el alcance actual.", "mode": "azure_live_rules_secops", "data": []}

    respuesta += _lista("Atender primero", [
        f"**{h.get('severidad', '').capitalize()}** · {h.get('titulo')} en `{h.get('name')}`. {h.get('recomendacion') or ''}".strip()
        for h in hallazgos[:6]
    ])
    return {"answer": respuesta, "mode": "azure_live_rules_secops", "data": []}

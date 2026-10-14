"""
Respuestas del motor de reglas para los agentes de costos y seguridad.

Incluye el motor general (`respuesta_general`, preguntas de inventario con
consultas KQL directas) y las respuestas de costos y seguridad.

Sin clave de Gemini (o si el modelo falla), el agente respondia siempre con las
reglas de inventario, sin importar a que agente se le preguntara: el de costos
contestaba "no logre interpretar tu pregunta" a "en que se va el gasto". Aqui
cada agente responde con los mismos servicios que alimentan su pestaña, de modo
que el chat sin IA sigue siendo util y nunca contradice al panel.
"""

import re
from typing import Any, Dict, List, Optional

from app.core import config
from app.core.texto import normalizar
from app.services import governance

from app.services.cost_overview_service import CostOverviewService

AHORRO = ("ahorr", "huerf", "optimiz", "desperdic", "reduc", "sin uso", "apagar")


def _money(valor: Optional[float], moneda: str = "USD") -> str:
    if valor is None:
        return "—"
    return f"{valor:,.2f} {moneda}"


def _lista(titulo: str, filas: List[str]) -> str:
    if not filas:
        return ""
    return f"\n**{titulo}**\n" + "\n".join(f"- {f}" for f in filas) + "\n"


def respuesta_finops(agente, pregunta: str, subs: Optional[List[str]]) -> Dict[str, Any]:
    texto = normalizar(pregunta)
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


def respuesta_general(agente, question: str) -> Dict[str, Any]:
    """Offline and rule-based fallback answering engine using direct KQL queries."""
    if not agente.azure.azure_connected:
        return {
            "answer": "⚠️ **Error de Conexión:** No estoy conectado a Azure. Revisa tus llaves del Service Principal en el archivo `.env` para habilitar las consultas en tiempo real.",
            "mode": "offline",
            "data": []
        }

    # Sin tildes ni mayusculas: "cuántos" y "cuantos" son la misma pregunta.
    question_lower = normalizar(question)

    # Rule: Questions about savings, technical debt lifecycle, and exceptions - disabled
    if any(normalizar(w) in question_lower for w in ["deuda", "deuda técnica", "excepción", "excepciones", "remediado", "aprobado"]):
        return {
            "answer": "El módulo de Gestión de Recomendaciones y Deuda Operacional se encuentra inhabilitado en esta plataforma por decisión administrativa. Si deseas realizar optimizaciones, por favor consulta al equipo SRE.",
            "mode": "azure_live_rule_fallback",
            "data": []
        }

    # 1. Ask about a specific resource name
    # El conector opcional (de/del/of) evita capturarlo como nombre del recurso:
    # "¿quién es el dueño de kv-x?" debe buscar `kv-x`, no `de`.
    resource_match = re.search(r'(?:dueno|owner|detalles|donde esta|recurso)(?:\s+(?:de|del|of))?\s+([a-zA-Z0-9\-_.]+)', question_lower)
    if resource_match:
        resource_name = resource_match.group(1)
        kql = f"resources | where name =~ '{resource_name}' | project name, type, resourceGroup, subscriptionId, location, tags"
        raw = agente.azure.query_azure_resource_graph(kql)

        if raw:
            res = raw[0]
            tags = res.get('tags', {}) or {}
            owner = tags.get('owner', tags.get('Owner', tags.get('OWNER', '❌ Sin tag owner')))
            env = tags.get('environment', tags.get('Environment', tags.get('ENVIRONMENT', 'Sin tag environment')))
            prov = tags.get('provisioning_method', tags.get('provisioned_by', 'portal (manual)'))

            md_resp = (
                f"### 🔍 Recurso Encontrado en Tiempo Real (Azure):\n\n"
                f"• **Nombre:** `{res['name']}`\n"
                f"• **Tipo:** `{res['type']}`\n"
                f"• **Dueño:** `{owner}`\n"
                f"• **Ambiente:** `{env}`\n"
                f"• **Resource Group:** `{res['resourceGroup']}`\n"
                f"• **Ubicación (Región):** `{res['location']}`\n"
                f"• **Método de Provisión:** `{prov.upper()}`\n"
                f"• **ID Suscripción:** `{res['subscriptionId']}`\n"
            )

            return {"answer": md_resp, "mode": "azure_live", "data": raw}
        else:
            # Si el usuario pregunta por diagnóstico, fallos o remediación de red de un recurso que no existe
            if any(normalizar(w) in question_lower for w in ["diagnosticar", "remediar", "failed", "fallado", "puerto", "nsg", "seguridad", "causas"]):
                # Responder teóricamente según el tipo o contexto
                if "nsg" in question_lower or "puerto" in question_lower:
                    md_resp = (
                        f"### 🛡️ Guía de Remediación de NSG (Teórica):\n\n"
                        f"El recurso `{resource_name}` no figura en el inventario real de Azure, pero para remediar reglas de NSG expuestas, sigue estos pasos:\n\n"
                        f"1. **Comando de Remediación (Azure CLI):**\n"
                        f"   ```bash\n"
                        f"   az network nsg rule update \\\n"
                        f"     --resource-group <mi-grupo-recursos> \\\n"
                        f"     --nsg-name <nombre-nsg> \\\n"
                        f"     --name <nombre-regla-SSH-RDP> \\\n"
                        f"     --source-address-prefixes <IP_Corporativa_Permitida> \\\n"
                        f"     --direction Inbound \\\n"
                        f"     --access Allow\n"
                        f"   ```\n"
                        f"2. **Procedimiento Recomendado:** Restringe el origen `*` o `0.0.0.0/0` a una VPN corporativa o Azure Bastion para mitigar riesgos de intrusión."
                    )
                else:  # Asumimos máquina virtual en estado Failed
                    md_resp = (
                        f"### ❌ Diagnóstico de Máquina Virtual en estado Failed (Teórico):\n\n"
                        f"El recurso `{resource_name}` no figura en el inventario real de Azure, pero para una máquina virtual (`microsoft.compute/virtualmachines`) en estado **Failed**, las causas más comunes y su diagnóstico son:\n\n"
                        f"1. **Causas Comunes de Failed State:**\n"
                        f"   - **Fallo de aprovisionamiento de extensiones:** Una extensión de Azure (ej. log analytics, network watcher, etc.) falló al instalarse o se colgó en el script de arranque.\n"
                        f"   - **Falta de recursos en el hipervisor (Allocation Failure):** Azure no encontró suficiente capacidad física en la región para arrancar el tamaño de VM solicitado.\n"
                        f"   - **Problemas en el arranque del OS:** Fallo en el sysprep o en la inicialización de los discos de boot.\n\n"
                        f"2. **Procedimiento de Diagnóstico & Remediación:**\n"
                        f"   * **Paso 1: Forzar una actualización de estado (Redeploy/Reapply):**\n"
                        f"     Esto limpia el estado transitorio fallido de Kudu/ARM sin borrar datos:\n"
                        f"     ```bash\n"
                        f"     az vm reapply --resource-group <mi-grupo-recursos> --name {resource_name}\n"
                        f"     ```\n"
                        f"   * **Paso 2: Comprobar los Logs de Aprovisionamiento:**\n"
                        f"     ```bash\n"
                        f"     az vm get-instance-view --resource-group <mi-grupo-recursos> --name {resource_name} --query \"instanceView.statuses\"\n"
                        f"     ```\n"
                        f"   * **Paso 3: Reiniciar o Redesplegar en otro host físico:**\n"
                        f"     ```bash\n"
                        f"     az vm redeploy --resource-group <mi-grupo-recursos> --name {resource_name}\n"
                        f"     ```"
                    )
                return {"answer": md_resp, "mode": "offline_diagnostic_fallback", "data": []}

            return {
                "answer": f"No encontré ningún recurso con el nombre `{resource_name}` en las suscripciones a las que tiene acceso el Service Principal.",
                "mode": "azure_live",
                "data": []
            }

    # 2. Tag Gaps / Policy violations
    if any(normalizar(w) in question_lower for w in ["tags", "políticas", "politica", "compliance", "gaps", "incumplen", "cumplen", "sin tag"]):
        kql_gaps = (
            "resources "
            + governance.kql_extends_tags_presentes(config.MANDATORY_TAGS)
            + f"| where not({governance.kql_todas_presentes(config.MANDATORY_TAGS)}) "
            "| limit 5 "
            "| project name, type, resourceGroup, tags"
        )
        raw_gaps = agente.azure.query_azure_resource_graph(kql_gaps)
        stats = agente.get_summary_stats()

        md_resp = (
            f"### 📋 Auditoría de Tags en Tiempo Real\n\n"
            f"• Cumplimiento Global de Tags: **{stats['tag_compliance_percentage']}%** de recursos cumpliendo.\n"
            f"• Recursos con incumplimiento: **{stats['missing_owner_tags']}** recursos (les falta al menos una de las {len(config.MANDATORY_TAGS)} etiquetas obligatorias).\n\n"
        )

        if 'missing_tags_detail' in stats:
            md_resp += "#### 📊 Conteo de etiquetas faltantes por categoría:\n"
            for tag_name, count in stats['missing_tags_detail'].items():
                md_resp += f"- Tag **{tag_name}**: Faltante en **{count}** recursos\n"
            md_resp += "\n"

        if raw_gaps:
            md_resp += "#### ⚠️ Recursos no cumplidores (Muestra):\n"
            for r in raw_gaps:
                tags = r.get('tags', {}) or {}
                tags_lower = {k.lower(): v for k, v in tags.items() if v}
                missing = [t for t in config.MANDATORY_TAGS if t.lower() not in tags_lower]
                md_resp += f"- `{r['name']}` ({r['type'].split('/')[-1]}) | RG: `{r['resourceGroup']}` | Faltan: {', '.join(missing)}\n"
        else:
            md_resp += "🎉 ¡Excelente! Todos los recursos analizados cumplen con las políticas de las " + str(len(config.MANDATORY_TAGS)) + " etiquetas obligatorias."

        return {"answer": md_resp, "mode": "azure_live", "data": raw_gaps}

    # 3. Terraform Adoption / Shadow IT
    if any(normalizar(w) in question_lower for w in ["terraform", "importar", "por fuera", "portal", "manual", "shadow"]):
        # Mismo criterio que el panel: sin evidencia de IaC y sin ser un
        # recurso derivado de otro. La version anterior negaba dos claves
        # con `!=`, que en KQL ni siquiera es lo contrario de la condicion
        # que contaba los gestionados, de modo que las dos cifras de la
        # misma respuesta se contradecian.
        kql_manual = (
            "resources "
            "| extend _t = todynamic(tolower(tostring(tags))) "
            "| extend _json = tolower(tostring(tags)) "
            f"| where not({governance.kql_tiene_iac()}) "
            f"| where not({governance.kql_es_derivado()}) "
            "| limit 5 "
            "| project name, type, resourceGroup, tags"
        )
        raw_manual = agente.azure.query_azure_resource_graph(kql_manual)
        stats = agente.get_summary_stats()

        md_resp = (
            f"### 🛠️ Auditoría de Cobertura IaC / Terraform\n\n"
            f"• Recursos administrados con Terraform: `{stats['terraform_managed']}` ({stats['terraform_percentage']}%)\n"
            f"• Recursos provistos vía Portal/Manual/Otros: `{stats['portal_managed']}` recursos\n\n"
        )

        if raw_manual:
            md_resp += "#### 📌 Recursos creados por fuera de Terraform (Muestra):\n"
            for r in raw_manual:
                md_resp += f"- **`{r['name']}`** ({r['type'].split('/')[-1]}) en RG: `{r['resourceGroup']}`\n"
        else:
            md_resp += "🎉 ¡Excelente! Toda tu infraestructura está bajo el control de Terraform."

        return {"answer": md_resp, "mode": "azure_live", "data": raw_manual}

    # 4. Summary / Resumen
    if any(normalizar(w) in question_lower for w in ["resumen", "estadisticas", "inventario", "cuantos recursos", "total"]):
        stats = agente.get_summary_stats()
        md_resp = (
            f"### 📊 Resumen Ejecutivo del Inventario de Azure (Live)\n\n"
            f"• **Total recursos descubiertos:** `{stats['total_resources']}`\n"
            f"• **Cumplimiento global de tags:** {stats['tag_compliance_percentage']}%\n\n"
            f"**Top Tipos de Recursos:**\n"
        )
        for rtype, count in list(stats['domain_distribution'].items())[:4]:
            md_resp += f"- *{rtype}:* {count} recursos\n"

        return {"answer": md_resp, "mode": "azure_live", "data": [stats]}

    # Generic search fallback
    matches = agente.search_resources(question, limit=5)
    if matches:
        md_resp = "Encontré los siguientes recursos que coinciden con tu consulta:\n\n"
        for r in matches:
            md_resp += f"- **`{r['name']}`** ({r['type'].split('/')[-1]}) | Owner: `{r['owner_confirmed']}` | RG: `{r['resourceGroup']}`\n"
        return {"answer": md_resp, "mode": "azure_live", "data": matches}

    return {
        "answer": "No logré interpretar tu pregunta. Intenta consultarme sobre:\n"
                  "- *¿Quién es el dueño del recurso [nombre]?*\n"
                  "- *¿Qué recursos no cumplen las políticas de tags?*\n"
                  "- *Resumen del inventario*",
        "mode": "azure_live",
        "data": []
    }

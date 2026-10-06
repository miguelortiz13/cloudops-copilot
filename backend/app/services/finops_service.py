"""
FinOpsService — Reporte de optimizacion financiera basado en gasto real.

Antes, el reporte de FinOps se construia con constantes inventadas: cada disco
huerfano "costaba" 8 USD, cada IP 3.65 USD, cada recurso 15.50 USD al mes, la
CPU promedio de toda VM era 2.4% y el consumo de presupuesto siempre 83.3%.
Esas cifras no se podian presentar a finanzas porque no correspondian a la
factura.

Este servicio reconstruye el mismo reporte cruzando tres fuentes reales:

* Azure Resource Graph  -> que recursos existen y en que estado estan.
* Azure Cost Management -> cuanto costo realmente cada recurso.
* Azure Monitor         -> que tan utilizados estan.

Cuando Cost Management no esta disponible (falta el rol Cost Management Reader,
o la API responde con limite de tasa) el reporte no se cae: vuelve a las
estimaciones por SKU, pero marca cada cifra con `cost_basis="estimated"` y
expone el motivo en el bloque `cost_data`, de modo que la interfaz pueda decir
con claridad si esta mostrando factura o estimacion.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core import config
from app.services import cost_service as cost_module
from app.services import kql, pricing

# Precios de referencia usados unicamente como respaldo cuando Cost Management
# no responde. Viven en services/pricing.py junto con el estimador por SKU y la
# tabla que se le pasa al agente, para que las tres cosas no puedan divergir.
FALLBACK_PRICES = pricing.FALLBACK_PRICES

# Umbral por debajo del cual una VM se considera infrautilizada.
UNDERUTILIZED_CPU_THRESHOLD = float(5.0)

# Cuantas VMs se inspeccionan con Azure Monitor por reporte. Leer metricas es
# una llamada HTTP por recurso, asi que se acota para no penalizar la respuesta.
MAX_VMS_TO_PROFILE = 25


class FinOpsService:
    """Construye el reporte de FinOps a partir de gasto y utilizacion reales."""

    def __init__(self, agent, cost_service, metrics_service):
        self.agent = agent
        self.cost = cost_service
        self.metrics = metrics_service

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_subscriptions(self, subscription_ids: Optional[List[str]]) -> List[str]:
        """Normaliza el scope: lo pedido, o todas las suscripciones visibles."""
        if subscription_ids:
            return [s for s in subscription_ids if s]
        try:
            kql = (
                "resourcecontainers "
                "| where type == 'microsoft.resources/subscriptions' "
                "| project subscriptionId"
            )
            raw = self.agent.query_azure_resource_graph(kql, subscriptions=[])
            resolved = [r.get("subscriptionId") for r in raw if r.get("subscriptionId")]
            if resolved:
                return resolved
        except Exception:
            pass
        import os

        sub_id = os.getenv("AZURE_SUBSCRIPTION_ID")
        return [sub_id] if sub_id else []

    # Las tres funciones de atribucion viven en services/cost_service.py, que es
    # la unica definicion de "cuanto cuesta este recurso y de donde sale la
    # cifra" en la plataforma: el panel y el chat del agente leen de ahi. Se
    # conservan estos alias porque los usan varios puntos del reporte.
    _subscription_of = staticmethod(cost_module.subscription_of)
    _monthly_from_window = staticmethod(cost_module.monthly_from_window)

    def _attach_costs(
        self,
        items: List[Dict[str, Any]],
        cost_map: Dict[str, float],
        window_days: int,
        covered_subs: Set[str],
        fallback,
    ) -> Dict[str, float]:
        """
        Anota cada recurso con su costo mensual y devuelve los totales.

        Delega en `cost_service.attach_costs`: la regla de facturado vs estimado
        es la misma que aplica el chat del agente, para que el mismo recurso no
        aparezca con dos cifras distintas segun donde se pregunte.
        """
        return cost_module.attach_costs(items, cost_map, window_days, covered_subs, fallback)

    # ------------------------------------------------------------------
    # Recoleccion de recursos huerfanos
    # ------------------------------------------------------------------

    def _collect_orphans(self, subs: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Consulta en paralelo las categorias de desperdicio.

        Todas las consultas proyectan `id`, que es la clave para cruzar cada
        recurso con su costo real en Cost Management.
        """
        queries = {
            "unattached_disks": kql.DISCOS_HUERFANOS,
            "unassociated_ips": kql.IPS_SIN_ASOCIAR,
            "orphaned_nics": kql.NICS_HUERFANAS,
            "empty_app_plans": kql.APP_PLANS_VACIOS,
            "old_snapshots": kql.SNAPSHOTS,
            "untagged_resources": kql.recursos_sin_tags(50),
            "resources_by_rg": kql.RECURSOS_POR_RG,
        }

        results: Dict[str, List[Dict[str, Any]]] = {}
        with ThreadPoolExecutor(max_workers=len(queries)) as executor:
            futures = {
                key: executor.submit(
                    self.agent.query_azure_resource_graph, kql, False, subs
                )
                for key, kql in queries.items()
            }
            for key, future in futures.items():
                try:
                    results[key] = future.result() or []
                except Exception as exc:
                    print(f"[FinOpsService] Consulta '{key}' fallo: {exc}")
                    results[key] = []
        return results

    # ------------------------------------------------------------------
    # Insights
    # ------------------------------------------------------------------

    def _compute_showback(
        self,
        cost_map: Dict[str, float],
        tag_map: Dict[str, Dict[str, str]],
        window_days: int,
        cost_status: str,
        currency: str,
    ) -> Dict[str, Any]:
        """
        Showback / chargeback cruzando el gasto real de cada recurso con sus tags.

        Se calcula en memoria en lugar de pedirle a Cost Management una consulta
        agrupada por cada tag: aquello gastaba cuatro llamadas de una API que
        limita con dureza la concurrencia, y ya se tiene el costo por recurso y
        los tags que devuelve Resource Graph. Como efecto secundario, el gasto
        sin atribuir queda explicito en la fila "Sin <tag>" en vez de diluirse.
        """
        # El showback solo puede construirse sobre gasto facturado: sin ninguna
        # suscripcion cubierta no hay nada que atribuir.
        if cost_status not in ("success", "partial"):
            return {"status": cost_status, "currency": currency, "items": []}

        dimensions = tuple(config.SHOWBACK_TAGS)
        totals: Dict[str, Dict[str, float]] = {d: {} for d in dimensions}

        for resource_id, cost in cost_map.items():
            tags = tag_map.get(resource_id, {})
            for dimension in dimensions:
                # Los tags de Azure no distinguen mayusculas de forma consistente.
                value = ""
                for key, val in tags.items():
                    if key.lower() == dimension.lower():
                        value = str(val or "").strip()
                        break
                label = value if value else f"Sin {dimension}"
                totals[dimension][label] = totals[dimension].get(label, 0.0) + cost

        items: List[Dict[str, Any]] = []
        for dimension in dimensions:
            for label, cost in sorted(
                totals[dimension].items(), key=lambda kv: kv[1], reverse=True
            ):
                items.append(
                    {
                        "dimension": dimension,
                        "value": label,
                        "actual_cost_usd": round(cost, 2),
                        "monthly_cost_usd": self._monthly_from_window(cost, window_days),
                        "currency": currency,
                        "cost_basis": "actual",
                    }
                )

        # Se propaga el estado real: con cobertura parcial la atribucion solo
        # abarca las suscripciones medidas, y la interfaz debe decirlo.
        return {"status": cost_status, "currency": currency, "items": items}

    def _build_anomalies(self, subs: List[str]) -> List[Dict[str, Any]]:
        """
        Anomalias de costo comparando la ultima semana contra la tendencia previa.

        Sustituye la heuristica anterior, que solo contaba recursos creados en
        los ultimos 7 dias y nunca miraba la factura.
        """
        # A diferencia del gasto por recurso, esta serie NO puede servirse de la
        # cache de un scope mas amplio: los importes vienen agregados por fecha,
        # sin el resource id que permita saber que suscripcion aporto cada peso.
        # Recortar a un subconjunto exigiria consultar de nuevo, asi que aqui la
        # clave de cache tiene que coincidir con el scope pedido.
        daily = self.cost.get_daily_costs(subs, days=30)
        daily_coverage = daily.get("coverage") or {}
        n_cov = len(daily_coverage.get("covered", []))
        n_unc = len(daily_coverage.get("denied", [])) + len(daily_coverage.get("failed", []))
        # Con cobertura parcial la serie es real pero incompleta: sirve para
        # detectar tendencias en las suscripciones medidas, y hay que decir que
        # las demas no estan siendo vigiladas.
        scope_note = (
            f" Cobertura: {n_cov} de {n_cov + n_unc} suscripciones; las restantes "
            f"no exponen datos de costo y no entran en este análisis."
            if n_unc else ""
        )

        if daily.get("status") not in ("success", "partial"):
            return [
                {
                    "title": "Sin datos de facturación disponibles",
                    "severity": "Info",
                    "description": (
                        "No se pudo consultar la serie diaria de Cost Management "
                        f"(estado: {daily.get('status')}). La detección de anomalías "
                        "requiere el rol Cost Management Reader sobre la suscripción."
                    ),
                    "recomm_action": "Asignar el rol Cost Management Reader al Service Principal.",
                }
            ]

        series = daily.get("series", {})
        if len(series) < 14:
            return [
                {
                    "title": "Histórico insuficiente para comparar",
                    "severity": "Info",
                    "description": (
                        f"Solo hay {len(series)} días de datos de costo consolidados; "
                        "se necesitan al menos 14 para comparar tendencias."
                    ),
                    "recomm_action": "Reintentar cuando Azure consolide más días de uso.",
                }
            ]

        dates = sorted(series.keys())
        recent = [series[d] for d in dates[-7:]]
        baseline = [series[d] for d in dates[:-7]]

        recent_avg = sum(recent) / len(recent)
        baseline_avg = sum(baseline) / len(baseline) if baseline else 0.0

        anomalies: List[Dict[str, Any]] = []
        if baseline_avg > 0:
            delta_pct = ((recent_avg - baseline_avg) / baseline_avg) * 100.0
            if delta_pct >= 20:
                anomalies.append(
                    {
                        "title": "Incremento sostenido del gasto diario",
                        "severity": "Critical" if delta_pct >= 50 else "Warning",
                        "description": (
                            f"El gasto medio de los últimos 7 días es de "
                            f"{recent_avg:,.2f} USD/día, un {delta_pct:,.1f}% por encima "
                            f"del promedio de los 23 días previos ({baseline_avg:,.2f} USD/día)."
                            f"{scope_note}"
                        ),
                        "recomm_action": (
                            "Revisar despliegues recientes y cambios de SKU en el periodo."
                        ),
                        "delta_percentage": round(delta_pct, 1),
                    }
                )
            elif delta_pct <= -20:
                anomalies.append(
                    {
                        "title": "Reducción significativa del gasto diario",
                        "severity": "Normal",
                        "description": (
                            f"El gasto medio de los últimos 7 días bajo a "
                            f"{recent_avg:,.2f} USD/día, un {abs(delta_pct):,.1f}% menos que "
                            f"el promedio previo ({baseline_avg:,.2f} USD/día)."
                        ),
                        "recomm_action": "Confirmar que la baja corresponde a optimizaciones y no a apagones.",
                        "delta_percentage": round(delta_pct, 1),
                    }
                )

        # Dias individuales muy por encima de la media del periodo.
        all_values = list(series.values())
        period_avg = sum(all_values) / len(all_values)
        spikes = [(d, v) for d, v in series.items() if period_avg > 0 and v > period_avg * 2]
        for date, value in spikes[-3:]:
            anomalies.append(
                {
                    "title": f"Pico de gasto el {date}",
                    "severity": "Warning",
                    "description": (
                        f"Ese día se facturaron {value:,.2f} USD, más del doble del "
                        f"promedio diario del periodo ({period_avg:,.2f} USD)."
                    ),
                    "recomm_action": "Identificar el servicio responsable en Cost Analysis para esa fecha.",
                }
            )

        if not anomalies:
            anomalies.append(
                {
                    "title": "Sin anomalias de costo detectadas",
                    "severity": "Normal",
                    "description": (
                        f"El gasto diario se mantiene estable alrededor de "
                        f"{period_avg:,.2f} USD/día en los ultimos 30 dias.{scope_note}"
                    ),
                    "recomm_action": "Continuar monitoreo rutinario.",
                }
            )
        return anomalies

    def _build_utilization(
        self,
        vms: List[Dict[str, Any]],
        cost_map: Dict[str, float],
        window_days: int,
        covered_subs: Set[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """VMs infrautilizadas y VMs de no-produccion encendidas, con datos reales."""
        # Solo tiene sentido medir CPU de las VMs encendidas.
        running = [
            vm for vm in vms
            if "running" in str(vm.get("powerState") or "").lower()
        ]

        # Leer metricas cuesta una llamada HTTP por recurso, asi que se perfila
        # un subconjunto. En un tenant con decenas de suscripciones ese
        # subconjunto no puede ser arbitrario: se priorizan las VMs de mayor
        # gasto conocido, que son las que hacen que el right-sizing valga la
        # pena. Las de suscripciones sin datos de costo van despues, ordenadas
        # de forma estable por nombre.
        def profiling_priority(vm: Dict[str, Any]) -> Tuple[float, str]:
            resource_id = str(vm.get("id") or "").lower()
            if self._subscription_of(resource_id) in covered_subs:
                return (-cost_map.get(resource_id, 0.0), str(vm.get("name") or ""))
            return (0.0, str(vm.get("name") or ""))

        running_sorted = sorted(running, key=profiling_priority)
        to_profile = running_sorted[:MAX_VMS_TO_PROFILE]
        cpu_map = self.metrics.get_average_cpu(
            [vm.get("id") for vm in to_profile if vm.get("id")], days=30
        )

        underutilized: List[Dict[str, Any]] = []
        for vm in to_profile:
            resource_id = str(vm.get("id") or "").lower()
            avg_cpu = cpu_map.get(resource_id)
            if avg_cpu is None or avg_cpu >= UNDERUTILIZED_CPU_THRESHOLD:
                continue

            covered = self._subscription_of(resource_id) in covered_subs
            billed = cost_map.get(resource_id) if covered else None
            if covered:
                monthly = self._monthly_from_window(billed or 0.0, window_days)
                basis = "actual"
            else:
                # Sin permisos de Cost Management sobre esa suscripcion no se
                # puede cuantificar el ahorro; el hallazgo de baja utilizacion
                # sigue siendo valido porque las metricas si son legibles.
                monthly = 0.0
                basis = "unavailable"

            underutilized.append(
                {
                    "name": vm.get("name"),
                    "size": vm.get("size"),
                    "resourceGroup": vm.get("resourceGroup"),
                    "avg_cpu_percentage": avg_cpu,
                    "monthly_cost_usd": monthly,
                    "cost_basis": basis,
                    "recomm": (
                        "CPU promedio bajo el umbral en 30 dias: evaluar right-sizing "
                        "a un SKU menor o apagado programado."
                    ),
                }
            )

        underutilized.sort(key=lambda item: item["monthly_cost_usd"], reverse=True)
        # Se deja constancia del alcance del muestreo para que la ausencia de
        # hallazgos no se lea como "no hay VMs infrautilizadas".
        profiling_scope = {
            "running_vms": len(running),
            "profiled_vms": len(to_profile),
        }

        # VMs de ambientes no productivos encendidas: el ahorro por apagarlas
        # fuera de horario laboral es proporcional a su costo real.
        non_prod_running: List[Dict[str, Any]] = []
        for vm in running:
            env = str(vm.get("env") or "").strip().lower()
            if env not in ("dev", "qa", "development", "devqa", "staging", "test"):
                continue
            resource_id = str(vm.get("id") or "").lower()
            covered = self._subscription_of(resource_id) in covered_subs
            billed = cost_map.get(resource_id) if covered else None
            if covered:
                monthly = self._monthly_from_window(billed or 0.0, window_days)
                # Encendida solo en horario laboral (9h x 5 dias = 45 de las 168
                # horas de la semana) se deja de pagar el 73% del tiempo.
                saving = round(monthly * 0.73, 2)
                basis = "actual"
            else:
                monthly = 0.0
                saving = 0.0
                basis = "unavailable"

            non_prod_running.append(
                {
                    "name": vm.get("name"),
                    "resourceGroup": vm.get("resourceGroup"),
                    "environment": vm.get("env"),
                    "status": "Encendida sin horario de apagado",
                    "monthly_cost_usd": monthly,
                    "saving_potential": saving,
                    "cost_basis": basis,
                }
            )

        non_prod_running.sort(key=lambda item: item["saving_potential"], reverse=True)
        return {
            "underutilized_resources": underutilized,
            "running_dev_vms_outside_hours": non_prod_running,
            "profiling_scope": profiling_scope,
        }

    def _build_reservations(
        self,
        vms: List[Dict[str, Any]],
        cost_map: Dict[str, float],
        window_days: int,
        covered_subs: Set[str],
    ) -> List[Dict[str, Any]]:
        """
        Candidatos a reserva, dimensionados con el gasto real de cada familia.

        Se agrupan las VMs encendidas por SKU y se suma su costo facturado; el
        ahorro se expresa como el descuento tipico de una reserva de 1 ano
        aplicado sobre ese gasto, no como una constante por instancia.
        """
        by_size: Dict[str, Dict[str, Any]] = {}
        for vm in vms:
            if "running" not in str(vm.get("powerState") or "").lower():
                continue
            size = vm.get("size")
            if not size:
                continue
            entry = by_size.setdefault(size, {"count": 0, "cost": 0.0, "has_cost": False})
            entry["count"] += 1
            resource_id = str(vm.get("id") or "").lower()
            if self._subscription_of(resource_id) in covered_subs:
                entry["cost"] += cost_map.get(resource_id, 0.0)
                entry["has_cost"] = True

        # Una reserva solo se justifica con carga estable: al menos 3 instancias.
        recommendations = []
        for size, entry in by_size.items():
            if entry["count"] < 3:
                continue
            monthly = self._monthly_from_window(entry["cost"], window_days)
            recommendations.append(
                {
                    "resource_type": "Virtual Machines",
                    "sku_size": size,
                    "quantity_instances": entry["count"],
                    "savings_plan_option": "Reservacion de 1 Ano",
                    "estimated_savings_percentage": 34,
                    "current_monthly_cost_usd": monthly,
                    "monthly_saving_usd": round(monthly * 0.34, 2),
                    "cost_basis": "actual" if entry["has_cost"] else "unavailable",
                }
            )

        recommendations.sort(key=lambda item: item["monthly_saving_usd"], reverse=True)
        return recommendations

    def _build_governance_lists(self, subs: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Recursos sin responsable y recursos no productivos sin fecha de expiracion."""
        kql_no_owner = kql.sin_responsable(25)
        kql_aging = kql.sin_expiracion(25)

        with ThreadPoolExecutor(max_workers=2) as executor:
            f_no_owner = executor.submit(
                self.agent.query_azure_resource_graph, kql_no_owner, False, subs
            )
            f_aging = executor.submit(
                self.agent.query_azure_resource_graph, kql_aging, False, subs
            )
            raw_no_owner = f_no_owner.result() or []
            raw_aging = f_aging.result() or []

        def shorten(items):
            return [
                {
                    "name": item.get("name"),
                    "type": str(item.get("type") or "").split("/")[-1],
                    "resourceGroup": item.get("resourceGroup"),
                }
                for item in items
            ]

        return {
            "no_owner_resources": shorten(raw_no_owner),
            "aging_resources_no_expiration": shorten(raw_aging),
        }

    def _analizar_atribucion(
        self,
        cost_map: Dict[str, float],
        tag_map: Dict[str, Dict[str, str]],
        nombre_map: Dict[str, Dict[str, str]],
        window_days: int,
        covered_subs: Set[str],
    ) -> Dict[str, Any]:
        """
        Gasto que no puede asignarse a ningun responsable, y quien lo causa.

        Esta es la cifra que mas mueve la aguja y la que el panel no destacaba.
        Medido en produccion: las palancas que el reporte ofrecia (huerfanos,
        apagado programado, reservas) suman ~2,2% del gasto, mientras que un
        37,7% no se puede atribuir a ningun cliente. Ademas las cuatro
        dimensiones daban exactamente la misma cifra, lo que revela que no son
        cuatro problemas distintos sino una sola poblacion de recursos sin
        ninguna etiqueta.

        Se devuelve la lista ordenada por gasto para que el equipo empiece por
        lo que cuesta, no por lo que aparezca primero.
        """
        sin_atribuir: List[Dict[str, Any]] = []
        total_medido = 0.0
        total_sin_atribuir = 0.0

        for resource_id, cost in cost_map.items():
            if self._subscription_of(resource_id) not in covered_subs:
                continue
            mensual = self._monthly_from_window(cost, window_days)
            total_medido += mensual

            tags = tag_map.get(resource_id, {})
            faltantes = []
            for dimension in config.SHOWBACK_TAGS:
                valor = ""
                for k, v in tags.items():
                    if k.lower() == dimension.lower():
                        valor = str(v or "").strip()
                        break
                if not valor:
                    faltantes.append(dimension)

            if faltantes:
                total_sin_atribuir += mensual
                meta = nombre_map.get(resource_id, {})
                sin_atribuir.append({
                    "id": resource_id,
                    "name": meta.get("name") or resource_id.rsplit("/", 1)[-1],
                    "type": str(meta.get("type") or "").split("/")[-1],
                    "resourceGroup": meta.get("resourceGroup"),
                    "monthly_cost_usd": mensual,
                    "missingTags": faltantes,
                })

        sin_atribuir.sort(key=lambda x: x["monthly_cost_usd"], reverse=True)

        return {
            "unattributed_monthly_usd": round(total_sin_atribuir, 2),
            "measured_monthly_usd": round(total_medido, 2),
            "unattributed_percentage": (
                round(total_sin_atribuir / total_medido * 100, 1) if total_medido else 0.0
            ),
            "resource_count": len(sin_atribuir),
            # Solo los mas caros: la cola larga no cambia ninguna decision.
            "top_resources": sin_atribuir[:25],
        }

    # ------------------------------------------------------------------
    # Reporte principal
    # ------------------------------------------------------------------

    def build_report(self, subscription_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Arma el reporte completo de FinOps."""
        subs = self._resolve_subscriptions(subscription_ids)

        # Etapa 1: todo lo que no depende de nada mas, en paralelo. Antes esto
        # corria en serie y el reporte tardaba mas de dos minutos, peligrosamente
        # cerca del corte de 230s del gateway de App Service.
        kql_vms = (
            "resources | where type =~ 'microsoft.compute/virtualmachines' "
            "| extend size = tostring(properties.hardwareProfile.vmSize) "
            "| extend env = coalesce(tostring(tags.Environment), tostring(tags.environment), "
            "tostring(tags.ENVIRONMENT), '') "
            "| extend powerState = tostring(properties.extended.instanceView.powerState.code) "
            "| project id, name, resourceGroup, size, env, powerState"
        )

        # Siete tareas independientes: una por worker para que ninguna espere turno.
        with ThreadPoolExecutor(max_workers=7) as executor:
            # `costs_for` en vez de `get_cost_by_resource`: la cache se indexa
            # por el scope completo de la consulta, asi que un panel filtrado a
            # una suscripcion no acierta en la entrada que dejo la precarga de
            # las treinta y lanza una consulta viva que Cost Management corta con
            # 429. Verificado en produccion: con el scope completo el panel daba
            # gasto facturado y, filtrado a una sola suscripcion, "estimated" del
            # mismo grupo que el chat mostraba facturado en 1181.68 USD.
            f_cost = executor.submit(self.cost.costs_for, subs)
            f_orphans = executor.submit(self._collect_orphans, subs)
            # Tags de todos los recursos, para atribuir el gasto por dimension.
            f_tags = executor.submit(
                self.agent.query_azure_resource_graph,
                "resources | project id, tags, name, type, resourceGroup",
                False,
                subs,
            )
            f_anomalies = executor.submit(self._build_anomalies, subs)
            f_budgets = executor.submit(self.cost.get_budgets, subs)
            f_governance = executor.submit(self._build_governance_lists, subs)
            # La lista de VMs la comparten utilizacion y reservas: una sola consulta.
            f_vms = executor.submit(
                self.agent.query_azure_resource_graph, kql_vms, False, subs
            )
            # Nombres de suscripcion, para poder nombrar en el reporte cuales
            # quedaron fuera de la medicion de costos.
            f_sub_names = executor.submit(
                self.agent.query_azure_resource_graph,
                "resourcecontainers "
                "| where type == 'microsoft.resources/subscriptions' "
                "| project subscriptionId, name",
                False,
                subs,
            )

            cost_result = f_cost.result()
            orphans = f_orphans.result()
            raw_tags = f_tags.result() or []
            anomalies = f_anomalies.result()
            budgets = f_budgets.result()
            governance = f_governance.result()
            vms = f_vms.result() or []
            raw_sub_names = f_sub_names.result() or []

        cost_status = cost_result.get("status")
        coverage = cost_result.get("coverage") or {"covered": [], "denied": [], "failed": []}
        # Conjunto de suscripciones con facturacion legible. Es la unidad de
        # decision de todo el reporte: cada recurso se marca real o estimado
        # segun pertenezca o no a una de estas.
        covered_subs = {s.lower() for s in coverage.get("covered", [])}
        cost_map: Dict[str, float] = cost_result.get("costs", {}) if covered_subs else {}
        window_days = cost_result.get("window_days") or 30
        currency = cost_result.get("currency", "USD")

        sub_names = {
            str(r.get("subscriptionId") or "").lower(): r.get("name")
            for r in raw_sub_names
            if r.get("subscriptionId")
        }

        tag_map: Dict[str, Dict[str, str]] = {
            str(row.get("id") or "").lower(): (row.get("tags") or {})
            for row in raw_tags
            if row.get("id")
        }
        nombre_map: Dict[str, Dict[str, str]] = {
            str(row.get("id") or "").lower(): {
                "name": row.get("name"),
                "type": row.get("type"),
                "resourceGroup": row.get("resourceGroup"),
            }
            for row in raw_tags
            if row.get("id")
        }
        atribucion = self._analizar_atribucion(
            cost_map, tag_map, nombre_map, window_days, covered_subs
        )
        showback = self._compute_showback(
            cost_map, tag_map, window_days, cost_status, currency
        )

        categories = [
            ("Discos Huérfanos", "unattached_disks",
             lambda item: (item.get("sizeGB") or 0) * FALLBACK_PRICES["disk_per_gb_month"]),
            ("IPs Sin Asociar", "unassociated_ips",
             lambda item: FALLBACK_PRICES["public_ip_month"]),
            ("NICs Huérfanas", "orphaned_nics",
             lambda item: FALLBACK_PRICES["nic_month"]),
            ("App Plans Vacíos", "empty_app_plans",
             lambda item: FALLBACK_PRICES["app_service_plan_month"]),
            ("Snapshots Antiguos", "old_snapshots",
             lambda item: (item.get("sizeGB") or 0) * FALLBACK_PRICES["snapshot_per_gb_month"]),
        ]

        breakdown: Dict[str, float] = {}
        savings_actual = 0.0
        savings_estimated = 0.0
        for label, key, fallback in categories:
            totals = self._attach_costs(
                orphans[key], cost_map, window_days, covered_subs, fallback
            )
            breakdown[label] = totals["total"]
            savings_actual += totals["actual"]
            savings_estimated += totals["estimated"]

        potential_savings = round(sum(breakdown.values()), 2)

        # Etapa 2: lo que necesita el mapa de costos y la lista de VMs.
        with ThreadPoolExecutor(max_workers=2) as executor:
            f_utilization = executor.submit(
                self._build_utilization, vms, cost_map, window_days, covered_subs
            )
            f_reservations = executor.submit(
                self._build_reservations, vms, cost_map, window_days, covered_subs
            )
            utilization = f_utilization.result()
            reservations = f_reservations.result()

        # El ahorro por apagado programado y por reservas se suma aparte del de
        # recursos huerfanos: son acciones distintas sobre recursos en uso.
        schedule_saving = round(
            sum(vm["saving_potential"] for vm in utilization["running_dev_vms_outside_hours"]), 2
        )
        reservation_saving = round(
            sum(r["monthly_saving_usd"] for r in reservations), 2
        )

        # Mensaje y metadatos de cobertura. Nunca se afirma "facturacion real" a
        # secas cuando el dato solo abarca parte del scope consultado.
        n_covered = len(coverage.get("covered", []))
        n_denied = len(coverage.get("denied", []))
        n_failed = len(coverage.get("failed", []))
        n_total = n_covered + n_denied + n_failed

        def sub_label(sub_id: str) -> str:
            return sub_names.get(sub_id.lower()) or sub_id

        if cost_status == "success":
            cost_message = (
                f"Facturación real de Azure Cost Management sobre "
                f"{n_covered} de {n_total} suscripciones del scope."
            )
        elif cost_status == "partial":
            # Se distingue la falta de permisos de un fallo transitorio: son dos
            # acciones distintas. Lo primero se resuelve asignando un rol; lo
            # segundo, reintentando. Mezclarlos haria pedir permisos que ya existen.
            motivos = []
            if n_denied:
                motivos.append(
                    f"{n_denied} sin el rol 'Cost Management Reader'"
                )
            if n_failed:
                motivos.append(
                    f"{n_failed} que no respondieron (límite de tasa o error transitorio)"
                )
            cost_message = (
                f"Facturación real de {n_covered} de {n_total} suscripciones; "
                + " y ".join(motivos)
                + ". Los recursos de esas suscripciones aparecen con costo estimado "
                "por SKU y su gasto NO está incluido en los totales."
            )
        elif cost_status == "unauthorized":
            cost_message = (
                f"El Service Principal no tiene el rol 'Cost Management Reader' sobre "
                f"ninguna de las {n_total} suscripciones del scope. Todas las cifras son "
                f"estimaciones por SKU, no facturación real."
            )
        elif cost_status == "offline":
            cost_message = "Sin conexión autenticada a Azure. Cifras estimadas por SKU."
        elif cost_status == "no_subscriptions":
            cost_message = "No hay suscripciones en el scope seleccionado."
        else:
            cost_message = (
                "Cost Management no respondió (límite de tasa o error transitorio). "
                "Las cifras mostradas son estimaciones por SKU; reintentar en unos minutos."
            )

        if cost_result.get("stale"):
            cost_message = (
                "Facturación real reutilizada de la última consulta exitosa; "
                "Cost Management está aplicando límite de tasa en este momento."
            )

        return {
            # Listas de recursos, ahora con id y costo real por fila.
            "unattached_disks": orphans["unattached_disks"],
            "unassociated_ips": orphans["unassociated_ips"],
            "orphaned_nics": orphans["orphaned_nics"],
            "empty_app_plans": orphans["empty_app_plans"],
            "old_snapshots": orphans["old_snapshots"],
            "untagged_resources": orphans["untagged_resources"],
            "resources_by_rg": orphans["resources_by_rg"],
            "estimated_savings_breakdown": breakdown,
            "savings_lifecycle": {
                "potential_savings_usd": potential_savings,
                # Desglose del ahorro de huerfanos segun su respaldo: cuanto sale
                # de la factura y cuanto de una estimacion por SKU.
                "potential_from_billing_usd": round(savings_actual, 2),
                "potential_from_estimate_usd": round(savings_estimated, 2),
                "schedule_savings_usd": schedule_saving,
                "reservation_savings_usd": reservation_saving,
                # El ciclo aprobado/realizado requiere persistencia de decisiones,
                # que hoy no existe: se reporta en cero en lugar de simularse.
                "approved_savings_usd": 0.0,
                "realized_savings_usd": 0.0,
            },
            # Atribucion del gasto: la palanca de mayor impacto del modulo.
            "cost_attribution": atribucion,
            "cost_data": {
                "status": cost_status,
                "source": "azure_cost_management" if covered_subs else "sku_estimate",
                # "partial" es un tercer estado de primera clase: hay factura
                # real, pero solo de una parte del scope.
                "basis": (
                    "actual" if cost_status == "success"
                    else "partial" if cost_status == "partial"
                    else "estimated"
                ),
                # Cost Management rechazo la consulta fresca y se reutilizo el
                # ultimo dato conocido: sigue siendo facturacion real, pero la
                # interfaz debe poder decir que no esta al minuto.
                "stale": bool(cost_result.get("stale")),
                "currency": currency,
                "window_days": window_days,
                "message": cost_message,
                "coverage": {
                    "total_subscriptions": n_total,
                    "covered_count": n_covered,
                    "uncovered_count": n_denied + n_failed,
                    "covered": [
                        {"id": s_id, "name": sub_label(s_id)}
                        for s_id in coverage.get("covered", [])
                    ],
                    "uncovered": [
                        {"id": s_id, "name": sub_label(s_id),
                         "reason": "sin_permisos" if s_id in coverage.get("denied", []) else "error"}
                        for s_id in list(coverage.get("denied", [])) + list(coverage.get("failed", []))
                    ],
                },
            },
            "insights": {
                "showback_chargeback": showback["items"],
                "showback_status": showback["status"],
                "budgets": budgets.get("budgets", []),
                "budgets_status": budgets.get("status"),
                "anomalies": anomalies,
                "no_owner_resources": governance["no_owner_resources"],
                "underutilized_resources": utilization["underutilized_resources"],
                "running_dev_vms_outside_hours": utilization["running_dev_vms_outside_hours"],
                "reservation_recommendations": reservations,
                "profiling_scope": utilization.get("profiling_scope", {}),
                "aging_resources_no_expiration": governance["aging_resources_no_expiration"],
            },
        }

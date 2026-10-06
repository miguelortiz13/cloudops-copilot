"""
Contenedor de servicios y estado compartido entre routers.

Vivia dentro de `main.py`, y cada router hacia `from main import get_services`:
un import circular que solo funcionaba porque `main` incluia los routers al
final del archivo. Aqui queda aislado, sin depender de FastAPI.

Los servicios se crean de forma perezosa en la primera peticion: el agente de
Azure autentica contra Entra ID al construirse, y hacerlo al importar el modulo
bloquearia el arranque del servidor (y de las pruebas) si Azure no responde.
"""

import os
import threading
import time
from datetime import datetime, timezone

from app.core import config
from app.services.cost_service import CostService
from app.services.finops_service import FinOpsService
from app.services.history_service import HistoryService
from app.services.inventory_service import InventoryService
from app.services.k8s_service import K8sService
from app.services.metrics_service import MetricsService
from app.services.risk_service import RiskService
from app.services.secops_service import SecOpsService
from app.services.tfstate_service import TfStateService

base_dir = config.BACKEND_DIR

_lock = threading.Lock()
_services = None


def get_services():
    """
    Devuelve la tupla de servicios, creandolos la primera vez.

    El orden es parte del contrato con los routers:
    (agent, inventory, history, cost, metrics, finops, secops, k8s, risk, tfstate)
    """
    global _services
    if _services is not None:
        return _services

    with _lock:
        if _services is not None:
            return _services
        print("Inicializando Azure Agent...")
        from app.agents.azure_agent import AzureInventoryAgent

        agent = AzureInventoryAgent()
        inventory = InventoryService(agent)
        # El indice de estados de Terraform es la unica fuente que demuestra
        # que recursos estan gestionados; ver services/tfstate_service.py.
        tfstate = TfStateService(agent)
        inventory.attach_tfstate(tfstate)
        history = HistoryService()
        cost = CostService(agent)
        metrics = MetricsService(agent)
        finops = FinOpsService(agent, cost, metrics)
        secops = SecOpsService(agent)
        risk = RiskService(secops, cost)
        k8s = K8sService(agent)
        # El chat responde con los mismos servicios que alimentan el panel:
        # asi comparte su cache —incluida la precarga de costos— y, sobre
        # todo, las mismas reglas de dominio.
        agent.attach_services(secops=secops, finops=finops, cost=cost, risk=risk)
        _services = (agent, inventory, history, cost, metrics,
                     finops, secops, k8s, risk, tfstate)
        print("Agent initialization complete!")
        return _services


# ----------------------------------------------------------------------
# Estado del pipeline de inventario (lo consultan /api/sync y el panel)
# ----------------------------------------------------------------------
sync_status = {
    "running": False,
    "last_run": "Nunca",
    "logs": "Consola inactiva. Presiona 'Sincronizar' para iniciar la extracción en tiempo real.",
    "error": None,
    "log_file": None,
}


# ----------------------------------------------------------------------
# Precarga de costos en segundo plano
# ----------------------------------------------------------------------
#
# Cost Management consolida el gasto una vez al dia y limita con dureza las
# consultas: con casi treinta suscripciones el reporte necesita ~56 llamadas y
# la cuota se agota antes de terminar, de modo que el usuario que abre el panel
# se lleva la espera y una cobertura degradada.
#
# Este hilo hace ese trabajo por adelantado y con pausas entre suscripciones.
# Las peticiones interactivas encuentran el dato ya en cache y nunca esperan a
# la API. Si la precarga falla, el reporte sigue funcionando: consulta bajo
# demanda con su presupuesto de tiempo acotado.

COST_WARM_ENABLED = os.getenv("COST_WARM_ENABLED", "true").strip().lower() in ("1", "true", "yes")
COST_WARM_INTERVAL_SECONDS = int(os.getenv("COST_WARM_INTERVAL_SECONDS", "21600"))
COST_WARM_INITIAL_DELAY_SECONDS = int(os.getenv("COST_WARM_INITIAL_DELAY_SECONDS", "20"))

cost_warm_status = {
    "enabled": COST_WARM_ENABLED,
    "last_run": None,
    "last_result": None,
    "running": False,
}


def _cost_warm_loop():
    """Refresca la cache de costos de forma periodica y pausada."""
    # Se deja respirar al arranque para no competir con las primeras peticiones.
    time.sleep(COST_WARM_INITIAL_DELAY_SECONDS)

    while True:
        try:
            subs, _ = get_services()[1].list_accessible_subscriptions()
            sub_ids = [x["subscriptionId"] for x in subs]

            # La cache de costos sobrevive a los reinicios, asi que un arranque
            # con dato fresco no tiene por que volver a gastar las ~56 llamadas
            # de la precarga: se espera a que venza y se refresca entonces. Sin
            # esto, varios despliegues seguidos agotaban la cuota.
            frescura = get_services()[3].cache_freshness(sub_ids)
            if sub_ids and not frescura["should_warm"]:
                cost_warm_status["last_result"] = {
                    "skipped": "cache_fresca",
                    "cache_age_seconds": frescura["age_seconds"],
                    "covered": frescura["covered"],
                }
                print(
                    "[CostWarm] Cache vigente (%s suscripciones, %s min de edad); "
                    "se refresca en %s min." % (
                        frescura["covered"],
                        int(frescura["age_seconds"] // 60),
                        int(frescura["remaining_seconds"] // 60),
                    )
                )
                time.sleep(max(60, frescura["remaining_seconds"]))
                continue

            if sub_ids:
                cost_warm_status["running"] = True
                resultado = get_services()[3].warm(sub_ids)
                cost_warm_status["last_result"] = resultado
                cost_warm_status["last_run"] = datetime.now(timezone.utc).isoformat()
                recuperadas = resultado.get("recovered_on_retry") or 0
                print(
                    "[CostWarm] %s suscripciones cubiertas de %s en %ss%s"
                    % (
                        resultado.get("covered"),
                        len(sub_ids),
                        resultado.get("elapsed_seconds"),
                        f" ({recuperadas} recuperadas en el reintento)" if recuperadas else "",
                    )
                )
        except Exception as exc:
            cost_warm_status["last_result"] = {"error": str(exc)}
            print(f"[CostWarm] Falló la precarga de costos: {exc}")
        finally:
            cost_warm_status["running"] = False
        time.sleep(COST_WARM_INTERVAL_SECONDS)


def start_cost_warmer() -> None:
    """Arranca el hilo de precarga si esta habilitado."""
    if COST_WARM_ENABLED:
        threading.Thread(target=_cost_warm_loop, name="cost-warm", daemon=True).start()
        print("[CostWarm] Precarga de costos activa (cada %sh)." % (COST_WARM_INTERVAL_SECONDS // 3600))
    else:
        print("[CostWarm] Precarga de costos desactivada.")

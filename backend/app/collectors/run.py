"""
Job diario de recoleccion (Container Apps Job, ADR 0007).

    python -m app.collectors.run                 # todos
    python -m app.collectors.run --only costs    # uno o varios, separados por coma

Orden: migraciones -> inventario -> costos -> hallazgos -> KPIs -> vistas
precalculadas para el panel (app/readmodel). Cada
recolector corre en su propia transaccion y deja su ejecucion en
`collector_runs`: un fallo en costos no impide guardar el inventario. El codigo
de salida es 1 si alguno termino en error, para que Container Apps lo marque
como fallido.

Toda la ejecucion abre la base una sola vez al dia: es la ventana que el
presupuesto del cupo gratuito asume (docs/plan/05-infraestructura.md).
"""

import argparse
import sys
import time
import traceback
from pathlib import Path
from typing import Callable, Dict, List

from app.collectors import costs, findings, inventory, kpis
from app.collectors.common import Contexto, Resultado, ahora
from app.db import engine as db
from app.db.models import CollectorRun

def precalcular_vistas(ctx: Contexto, session) -> Resultado:
    """Deja las vistas por defecto del panel en la cache compartida (app/readmodel)."""
    from app.readmodel.service import precalentar

    return Resultado(items=precalentar(session))


RECOLECTORES: Dict[str, Callable] = {
    "inventory": inventory.recolectar,
    "costs": costs.recolectar,
    "findings": findings.recolectar,
    "kpis": kpis.recolectar,
    "readmodel": precalcular_vistas,
}

# Reanudar una base serverless pausada puede tardar; el job tiene tiempo.
ESPERA_BASE_SEGUNDOS = 240


def migrar() -> None:
    from alembic import command
    from alembic.config import Config

    backend = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "migrations"))
    command.upgrade(cfg, "head")


def ejecutar(nombre: str, funcion: Callable, ctx: Contexto) -> str:
    """Corre un recolector registrando inicio, fin y resultado."""
    with db.session_scope(ESPERA_BASE_SEGUNDOS) as s:
        corrida = CollectorRun(collector=nombre, started_at=ahora(), status="en_curso", items=0, detail={})
        s.add(corrida)
        s.flush()
        corrida_id = corrida.id

    inicio = time.monotonic()
    try:
        with db.session_scope(ESPERA_BASE_SEGUNDOS) as s:
            resultado: Resultado = funcion(ctx, s)
        estado, items, detalle, error = resultado.status, resultado.items, resultado.detail, None
    except Exception as exc:
        traceback.print_exc()
        estado, items, detalle, error = "error", 0, {}, f"{type(exc).__name__}: {exc}"[:4000]

    detalle = {**detalle, "seconds": round(time.monotonic() - inicio, 1)}
    with db.session_scope(ESPERA_BASE_SEGUNDOS) as s:
        corrida = s.get(CollectorRun, corrida_id)
        corrida.finished_at, corrida.status, corrida.items = ahora(), estado, items
        corrida.detail, corrida.error = detalle, error
    print(f"[recolector] {nombre}: {estado} ({items} elementos) {detalle}{' - ' + error if error else ''}")
    return estado


def construir_contexto() -> Contexto:
    from app.providers.azure import AzureClient
    from app.services.cost_service import CostService
    from app.services.inventory_service import InventoryService
    from app.services.secops_service import SecOpsService
    from app.services.tfstate_service import TfStateService

    azure = AzureClient()
    if not azure.azure_connected:
        raise RuntimeError("Sin conexion autenticada con Azure.")
    inventario = InventoryService(azure)
    inventario.attach_tfstate(TfStateService(azure))
    subs, avisos = inventario.list_accessible_subscriptions()
    if not subs:
        raise RuntimeError("La identidad no ve ninguna suscripcion: " + "; ".join(avisos))
    return Contexto(
        azure=azure, inventory=inventario, cost=CostService(azure), secops=SecOpsService(azure),
        subscription_ids=[s["subscriptionId"] for s in subs],
        subscription_names={s["subscriptionId"]: s.get("displayName") or s["subscriptionId"] for s in subs},
    )


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Recolectores de CloudOps Copilot")
    parser.add_argument("--only", default="", help="Recolectores separados por coma: " + ",".join(RECOLECTORES))
    parser.add_argument("--skip-migrations", action="store_true")
    args = parser.parse_args(argv)

    elegidos = [n.strip() for n in args.only.split(",") if n.strip()] or list(RECOLECTORES)
    desconocidos = [n for n in elegidos if n not in RECOLECTORES]
    if desconocidos:
        parser.error(f"Recolectores desconocidos: {', '.join(desconocidos)}")

    if not db.is_configured():
        print("[recolector] Sin base de datos configurada (DB_SERVER/DB_NAME o DATABASE_URL).")
        return 2
    # Despierta la base una vez y espera a que este disponible.
    db.connect(ESPERA_BASE_SEGUNDOS).close()
    if not args.skip_migrations:
        migrar()

    ctx = construir_contexto()
    print(f"[recolector] {len(ctx.subscription_ids)} suscripcion(es): {', '.join(elegidos)}")
    estados = [ejecutar(n, RECOLECTORES[n], ctx) for n in elegidos]
    return 1 if "error" in estados else 0


if __name__ == "__main__":
    sys.exit(main())

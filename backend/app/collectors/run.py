"""
Job diario de recoleccion (Container Apps Job, ADR 0007).

    python -m app.collectors.run                 # todos
    python -m app.collectors.run --only costs    # uno o varios, separados por coma

Orden: migraciones -> inventario (Azure y, si esta configurado, AWS) -> clasificacion ISO
(costos de AWS despues de los de Azure) -> costos -> hallazgos -> KPIs -> cache de la
vision general de costos -> vistas precalculadas para el panel (app/readmodel). Cada
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

from app.collectors import classification, costs, findings, inventory, kpis
from app.collectors.common import Contexto, Resultado, ahora
from app.db import engine as db
from app.db.models import CollectorRun

def precalentar_costos_en_vivo(ctx: Contexto, session) -> Resultado:
    """
    Deja lista la cache de la vision general de costos (consulta en vivo a Cost
    Management) y la vision ya armada en el almacenamiento compartido con el
    API. Asi el API no precarga en cada arranque en frio ni hace esperar al
    usuario.
    """
    from app.readmodel import cache
    from app.services.cost_overview_service import CostOverviewService

    r = ctx.cost.warm(ctx.subscription_ids, pace_seconds=2.5)
    faltan = len(ctx.subscription_ids) - (r.get("covered") or 0)
    # Con los costos ya en cache, la vision general sale sin esperar: se deja
    # armada para la vista por defecto (todas las suscripciones).
    try:
        cache.guardar(cache.clave("cost_overview", subscriptions=""), CostOverviewService(ctx.azure, ctx.cost).build())
        vision = True
    except Exception as exc:  # sin la vision armada, el API la arma en la primera visita
        print(f"[recolector] Vision general de costos no precalculada: {exc}")
        vision = False
    return Resultado(items=r.get("covered") or 0, status="parcial" if faltan or not vision else "ok",
                     detail={"subscriptions": len(ctx.subscription_ids), "recovered_on_retry": r.get("recovered_on_retry"),
                             "overview": vision})


def _contexto_aws(ctx: Contexto) -> Contexto:
    from app.providers.aws.provider import AwsProvider

    proveedor = AwsProvider.desde_entorno()
    cuentas = proveedor.cuentas()
    if not cuentas:
        raise RuntimeError("La identidad no ve ninguna cuenta de AWS.")
    return Contexto(azure=None, inventory=None, cost=None, secops=None, momento=ctx.momento,
                    proveedor=proveedor, cuentas=cuentas)


def inventario_aws(ctx: Contexto, session) -> Resultado:
    """
    Inventario de AWS con el mismo recolector, sobre su propio proveedor y
    cuentas. Va en su propia ejecucion: si AWS falla, Azure no se entera.
    """
    aws = _contexto_aws(ctx)
    resultado = inventory.recolectar(aws, session)
    resultado.detail["identity"] = aws.proveedor.identidad
    return resultado


def costos_aws(ctx: Contexto, session) -> Resultado:
    """Costos de AWS desde el export FOCUS (Athena), en su propia ejecucion."""
    from app.providers.base import Capacidad

    aws = _contexto_aws(ctx)
    if Capacidad.COSTOS not in aws.proveedor.capacidades():
        return Resultado(status="parcial", detail={"covered_accounts": [], "reason": "Export de costos no configurado."})
    if not aws.proveedor.export_entregado():
        # La primera entrega tarda hasta 24 h: sin dato todavia, no es un fallo del job.
        return Resultado(status="parcial", detail={"covered_accounts": [],
                                                   "reason": "El export de costos todavia no entrego datos."})
    return costs.recolectar(aws, session, nombre="costs_aws", fuente="export")


def precalcular_vistas(ctx: Contexto, session) -> Resultado:
    """Deja las vistas por defecto del panel en la cache compartida (app/readmodel)."""
    from app.readmodel.service import precalentar

    return Resultado(items=precalentar(session))


RECOLECTORES: Dict[str, Callable] = {
    "inventory": inventory.recolectar,
    "inventory_aws": inventario_aws,
    "classification": classification.recolectar,
    "costs": costs.recolectar,
    "costs_aws": costos_aws,
    "findings": findings.recolectar,
    "kpis": kpis.recolectar,
    "costcache": precalentar_costos_en_vivo,
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
    """
    El proveedor configurado (hoy Azure) y sus cuentas. Los recolectores del
    modelo canonico solo usan `proveedor` y `cuentas`; los servicios quedan para
    los pasos propios de Azure (KPIs de gobernanza y cache de costos del panel).
    """
    from app.providers.azure import AzureClient
    from app.providers.azure.provider import AzureProvider

    azure = AzureClient()
    if not azure.azure_connected:
        raise RuntimeError("Sin conexion autenticada con Azure.")
    proveedor = AzureProvider.desde_cliente(azure)
    cuentas = proveedor.cuentas()
    if not cuentas:
        raise RuntimeError("La identidad no ve ninguna suscripcion.")
    return Contexto(
        azure=azure, inventory=proveedor._inventory, cost=proveedor._cost, secops=proveedor._secops,
        subscription_ids=[c.native_id for c in cuentas],
        subscription_names={c.native_id: c.name for c in cuentas},
        proveedor=proveedor, cuentas=cuentas,
    )


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Recolectores de CloudOps Copilot")
    parser.add_argument("--only", default="", help="Recolectores separados por coma: " + ",".join(RECOLECTORES))
    parser.add_argument("--skip-migrations", action="store_true")
    args = parser.parse_args(argv)

    from app.providers.aws.provider import AwsProvider

    por_defecto = [n for n in RECOLECTORES if not n.endswith("_aws") or AwsProvider.configurado()]
    elegidos = [n.strip() for n in args.only.split(",") if n.strip()] or por_defecto
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

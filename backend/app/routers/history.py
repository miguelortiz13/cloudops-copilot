"""
Vistas que leen de la base: historia de costos, KPIs, gestion de hallazgos e
inventario multinube.

Responden desde la cache que deja el recolector (ver app/readmodel). Sin base,
o con la base pausada por haber agotado el cupo gratuito del mes, responden 503
y el panel vuelve a las vistas en vivo.
"""

import csv
import io
from datetime import date
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.audit import auditar
from app.core.authz import Usuario, requiere
from app.db import engine as db
from app.readmodel import queries, service

router = APIRouter(tags=["history"])


def _no_disponible(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=f"Historia no disponible: {exc}")


def _guardia():
    if not db.is_configured():
        raise HTTPException(status_code=503, detail="Historia no disponible: la base de datos no está configurada.")


def _cuentas_del_filtro(accounts: Optional[str]) -> Optional[List[str]]:
    """uids del filtro del panel ("azure:sub/...,aws:account/..."); vacío = todas."""
    cuentas = [c.strip() for c in (accounts or "").split(",") if c.strip()]
    if len(cuentas) > 500 or any(len(c) > 200 for c in cuentas):
        raise HTTPException(status_code=400, detail="Filtro de cuentas inválido.")
    return cuentas or None


@router.get("/api/accounts")
def accounts():
    """Cuentas de todas las nubes para el filtro del panel (precalculado)."""
    if not db.is_configured():
        return {"configured": False, "providers": [], "accounts": []}
    try:
        return service.cuentas()
    except db.DatabaseUnavailable as exc:
        raise _no_disponible(exc)


@router.get("/api/history/costs")
def history_costs(period: str = "30d", accounts: Optional[str] = None):
    _guardia()
    try:
        return service.costos(period, _cuentas_del_filtro(accounts))
    except queries.PeriodoInvalido as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except db.DatabaseUnavailable as exc:
        raise _no_disponible(exc)


@router.get("/api/history/kpis")
def history_kpis(days: int = queries.DIAS_KPI_POR_DEFECTO):
    _guardia()
    if not 7 <= days <= 400:
        raise HTTPException(status_code=400, detail="days debe estar entre 7 y 400.")
    try:
        return service.kpis(days)
    except db.DatabaseUnavailable as exc:
        raise _no_disponible(exc)


@router.get("/api/findings")
def list_findings():
    _guardia()
    try:
        return service.hallazgos()
    except db.DatabaseUnavailable as exc:
        raise _no_disponible(exc)


@router.get("/api/findings/{finding_id}/events")
def finding_events(finding_id: int):
    _guardia()
    try:
        return service.eventos(finding_id)
    except db.DatabaseUnavailable as exc:
        raise _no_disponible(exc)


class CambioDeEstado(BaseModel):
    status: Literal["abierto", "asumido", "aceptado"]
    note: Optional[str] = Field(default=None, max_length=2000)
    accepted_until: Optional[date] = None
    owner: Optional[str] = Field(default=None, max_length=320)


@router.post("/api/findings/{finding_id}/status")
def change_finding_status(finding_id: int, body: CambioDeEstado, usuario: Usuario = requiere("operador")):
    _guardia()
    try:
        resultado = service.cambiar_estado(finding_id, body.status, usuario.actor, body.note, body.accepted_until, body.owner)
        auditar(usuario, "hallazgo.estado", objetivo=resultado["resource_uid"], detalle={
            "finding_id": finding_id, "rule": resultado["rule_id"], "status": body.status,
            "accepted_until": body.accepted_until, "note": body.note})
        return resultado
    except service.CambioInvalido as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except db.DatabaseUnavailable as exc:
        raise _no_disponible(exc)


@router.get("/api/inventory/report")
def inventory_report():
    """Inventario de todas las nubes por cuenta, tipo y región, con gasto y cobertura de Terraform (precalculado)."""
    _guardia()
    try:
        return service.inventario_multinube()
    except db.DatabaseUnavailable as exc:
        raise _no_disponible(exc)


COLUMNAS_INVENTARIO = (
    ("provider", "Nube"), ("account", "Cuenta"), ("name", "Recurso"), ("type", "Tipo"), ("native_type", "Tipo nativo"),
    ("region", "Región"), ("group", "Grupo"), ("environment", "Ambiente"), ("classification", "Clasificación"),
    ("cost_30d", "Gasto 30 días"), ("currency", "Moneda"), ("in_iac", "En Terraform"), ("created_by", "Creado por"),
    ("first_seen", "Visto desde"), ("uid", "Identificador"),
)


@router.get("/api/inventory/report/export")
def inventory_report_export(accounts: Optional[str] = None):
    """El reporte de inventario en CSV (UTF-8 con BOM para que Excel respete las tildes), con el filtro del panel."""
    _guardia()
    cuentas = _cuentas_del_filtro(accounts)
    try:
        datos = service.inventario_multinube()
    except db.DatabaseUnavailable as exc:
        raise _no_disponible(exc)
    salida = io.StringIO()
    salida.write("\ufeff")
    escritor = csv.writer(salida)
    escritor.writerow([titulo for _, titulo in COLUMNAS_INVENTARIO])
    for r in datos["resources"]:
        if cuentas and r["account_uid"] not in cuentas:
            continue
        v = [r.get(campo) for campo, _ in COLUMNAS_INVENTARIO]
        escritor.writerow(["Sí" if x is True else "No" if x is False else "" if x is None else x for x in v])
    return StreamingResponse(iter([salida.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="inventario-multinube.csv"'})

"""
Cumplimiento: estado por control (CIS, ISO 27001), catalogo de reglas y
clasificacion ISO de activos.

Lee de la base a traves de app/readmodel (cache del recolector primero).
Reemplaza a `/api/governance/iso`, que leia la hoja `12_inventario_iso` del
Excel del pipeline.
"""

import csv
import io
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.audit import auditar
from app.core.authz import Usuario, requiere
from app.db import engine as db
from app.readmodel import service
from app.routers.history import _guardia, _no_disponible

router = APIRouter(tags=["compliance"])

Nivel = Field(ge=1, le=3)


@router.get("/api/compliance")
def compliance_status():
    """Marcos con el estado de cada control evaluado y el catalogo de reglas."""
    _guardia()
    try:
        return service.cumplimiento()
    except db.DatabaseUnavailable as exc:
        raise _no_disponible(exc)


@router.get("/api/compliance/assets")
def compliance_assets():
    """Activos con su clasificacion ISO 27001 (A.5.9, A.5.12)."""
    _guardia()
    try:
        return service.activos()
    except db.DatabaseUnavailable as exc:
        raise _no_disponible(exc)


COLUMNAS_CSV = [
    ("name", "Activo"), ("type", "Tipo"), ("group", "Grupo de recursos"), ("account", "Suscripción"),
    ("environment", "Ambiente"), ("classification", "Clasificación"), ("confidentiality", "Confidencialidad"),
    ("integrity", "Integridad"), ("availability", "Disponibilidad"), ("score", "Criticidad"),
    ("risk_required", "Requiere análisis de riesgo"), ("custodian", "Custodio"), ("method", "Método"),
    ("reason", "Motivo"), ("updated_by", "Actualizado por"), ("updated_at", "Actualizado"),
    ("open_findings", "Hallazgos activos"), ("uid", "Id"),
]


@router.get("/api/compliance/assets/export")
def compliance_assets_export():
    """Inventario clasificado en CSV (UTF-8 con BOM para que Excel respete las tildes)."""
    _guardia()
    try:
        datos = service.activos()
    except db.DatabaseUnavailable as exc:
        raise _no_disponible(exc)
    salida = io.StringIO()
    salida.write("﻿")
    escritor = csv.writer(salida)
    escritor.writerow([titulo for _, titulo in COLUMNAS_CSV])
    for a in datos["items"]:
        fila = []
        for campo, _ in COLUMNAS_CSV:
            v = a.get(campo)
            fila.append("Sí" if v is True else "No" if v is False else "" if v is None else v)
        escritor.writerow(fila)
    return StreamingResponse(iter([salida.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="activos-clasificados.csv"'})


class Clasificacion(BaseModel):
    resource_uid: str = Field(max_length=450)
    classification: Literal["Confidencial", "Restringido", "Uso interno"]
    confidentiality: int = Nivel
    integrity: int = Nivel
    availability: int = Nivel
    risk_required: bool
    reason: str = Field(min_length=1, max_length=2000)
    custodian: Optional[str] = Field(default=None, max_length=320)


class Recurso(BaseModel):
    resource_uid: str = Field(max_length=450)


def _errores(funcion):
    try:
        return funcion()
    except service.CambioInvalido as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except db.DatabaseUnavailable as exc:
        raise _no_disponible(exc)


@router.post("/api/compliance/assets/classification")
def set_asset_classification(body: Clasificacion, usuario: Usuario = requiere("operador")):
    """Clasificacion manual: el recolector la respeta hasta que se restaure la automatica."""
    _guardia()
    activo = _errores(lambda: service.clasificar_a_mano(
        body.resource_uid, body.classification, body.confidentiality, body.integrity, body.availability,
        body.risk_required, body.reason, body.custodian, usuario.actor))
    auditar(usuario, "activo.clasificacion", objetivo=body.resource_uid, detalle={
        "classification": body.classification, "cid": [body.confidentiality, body.integrity, body.availability],
        "risk_required": body.risk_required, "reason": body.reason, "custodian": activo.get("custodian")})
    return activo


@router.post("/api/compliance/assets/classification/restore")
def restore_asset_classification(body: Recurso, usuario: Usuario = requiere("operador")):
    """Devuelve el activo a la clasificacion automatica."""
    _guardia()
    activo = _errores(lambda: service.restaurar_automatica(body.resource_uid, usuario.actor))
    auditar(usuario, "activo.clasificacion_automatica", objetivo=body.resource_uid,
            detalle={"classification": activo.get("classification")})
    return activo

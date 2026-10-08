"""Quien soy y que puedo hacer: el panel muestra u oculta acciones con esto."""

from fastapi import APIRouter, Request

from app.core.authz import usuario_actual

router = APIRouter(tags=["session"])


@router.get("/api/me")
def me(request: Request):
    return usuario_actual(request).a_dict()

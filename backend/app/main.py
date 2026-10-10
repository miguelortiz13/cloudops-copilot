"""
Punto de entrada del API de CloudOps Copilot.

Ejecutar en local desde backend/:

    uvicorn app.main:app --reload

`config` se importa primero porque carga el `.env`, y varios servicios leen sus
variables en tiempo de import.
"""

from contextlib import asynccontextmanager

from app.core import config  # noqa: F401  (carga el .env antes que el resto)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.container import start_cost_warmer
from app.routers import (
    admin, chat, compliance, finops, history, iac, inventory, k8s, legacy, me, recommendations, secops, sync, teams,
)
from app.services.auth import auth_middleware, startup_banner
from app.services.bot_auth import startup_banner as bot_startup_banner


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.ensure_data_dirs()
    startup_banner()
    bot_startup_banner()
    start_cost_warmer()
    yield


app = FastAPI(
    title=config.APP_NAME,
    version=config.APP_VERSION,
    description=(
        "Copiloto de operaciones cloud para Azure: inventario y gobernanza, "
        "FinOps, SecOps, cobertura de IaC y agentes conversacionales."
    ),
    lifespan=lifespan,
)

app.middleware("http")(auth_middleware)

# CORS se registra despues para que quede por fuera: Starlette aplica los
# middlewares en orden inverso al de registro, y las respuestas 401 del
# middleware de autenticacion deben salir con cabeceras CORS para que el
# navegador pueda leer el motivo del rechazo. Nunca "*" junto con
# allow_credentials, que el navegador rechaza y ademas expone el API al mundo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

for modulo in (k8s, finops, secops, inventory, iac, sync, teams, recommendations, chat, admin, history, compliance, me,
               legacy):
    app.include_router(modulo.router)


from fastapi import APIRouter, BackgroundTasks
from app.schemas.inventory import *
from app.schemas.k8s import *
from app.schemas.requests import *
from app.core.audit import auditar
from app.core.authz import Usuario, requiere
from app.core.container import sync_status
from app.routers.legacy import run_inventory_pipeline


router = APIRouter(tags=['sync'])

@router.post("/api/sync")
def trigger_sync(background_tasks: BackgroundTasks, usuario: Usuario = requiere("operador")):
    if sync_status["running"]:
        return {"status": "running", "message": "La sincronización ya está ejecutándose."}
        
    auditar(usuario, "inventario.sincronizar")
    background_tasks.add_task(run_inventory_pipeline)
    return {"status": "started", "message": "Sincronización de inventario iniciada en segundo plano."}


@router.get("/api/sync/status")
def get_sync_status():
    if sync_status["running"] and sync_status["log_file"]:
        try:
            with open(sync_status["log_file"], "r") as f:
                sync_status["logs"] = f.read()
        except Exception:
            pass
    return sync_status



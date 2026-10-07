
from fastapi import APIRouter, HTTPException
from typing import List, Optional
from app.schemas.inventory import *
from app.schemas.k8s import *
from app.schemas.requests import *
from app.core import config
from app.core.deps import AgentDep, HistoryDep, InventoryDep
import os
from pydantic import BaseModel


router = APIRouter(tags=['inventory'])

@router.get("/api/inventory/snapshots")
def list_snapshots():
    import time
    
    snapshots_dir = config.SNAPSHOTS_DIR
    if not snapshots_dir.exists():
        return []
    
    files = []
    for p in sorted(snapshots_dir.glob("*.xlsx"), reverse=True):
        stat = p.stat()
        files.append({
            "filename": p.name,
            "size": stat.st_size,
            "created_at": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))
        })
    return files

from fastapi.responses import FileResponse


@router.get("/api/inventory/download/{filename}")
def download_snapshot(filename: str):
    
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido.")
        
    snapshots_dir = config.SNAPSHOTS_DIR
    file_path = snapshots_dir / filename
    
    if filename == "Azure_IaC_Inventario.xlsx":
        file_path = config.INVENTORY_EXCEL
        
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")
        
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

class WebhookTestRequest(BaseModel):
    webhook_url: str
    alert_type: str


@router.get("/api/inventory/health")
def inventory_health(agent: AgentDep, inventory: InventoryDep):
    """Health check for the inventory module. Never exposes secrets."""
    from datetime import datetime, timezone
    has_creds = all([
        os.getenv("AZURE_TENANT_ID"),
        os.getenv("AZURE_CLIENT_ID") or os.getenv("AZURE_READER_CLIENT_ID"),
        os.getenv("AZURE_CLIENT_SECRET") or os.getenv("AZURE_READER_CLIENT_SECRET")
    ])
    return {
        "status": "ok" if agent.azure_connected else "degraded",
        "azureConnected": agent.azure_connected,
        "credentialsConfigured": has_creds,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cacheEnabled": True,
        "cacheTtlSeconds": inventory._cache_ttl,
        "version": config.APP_VERSION
    }



@router.get("/api/inventory/subscriptions")
def inventory_subscriptions(inventory: InventoryDep):
    """Lists all Azure subscriptions accessible to the Service Principal."""
    subs, warnings = inventory.list_accessible_subscriptions()
    if not subs and warnings:
        return {
            "subscriptions": [],
            "warnings": warnings,
            "total": 0
        }
    return {
        "subscriptions": subs,
        "warnings": warnings,
        "total": len(subs)
    }



@router.post("/api/inventory/resources")
def inventory_resources(inventory: InventoryDep, req: InventoryResourcesRequest):
    """Returns paginated, filtered inventory resources with normalized governance data."""
    try:
        result = inventory.get_resources(req.model_dump())
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar recursos: {str(e)}")



@router.post("/api/inventory/summary")
def inventory_summary(inventory: InventoryDep, history: HistoryDep, req: SubscriptionSummaryRequest):
    """
    KPIs globales del inventario.

    De paso registra el punto historico del dia, que alimenta la vista de
    tendencia sin necesidad de un proceso aparte.
    """
    try:
        result = inventory.get_summary(
            subscription_ids=req.subscriptionIds or [],
            force_refresh=req.forceRefresh
        )
        try:
            history.record(req.subscriptionIds or [], result)
        except Exception as exc:
            # La tendencia es un extra: nunca debe impedir devolver los KPIs.
            print(f"No se pudo registrar el punto historico: {exc}")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/api/inventory/tag-compliance")
def inventory_tag_compliance(inventory: InventoryDep, req: SubscriptionSummaryRequest):
    """Returns tag compliance matrix for mandatory tags."""
    try:
        result = inventory.get_tag_compliance(req.subscriptionIds, req.forceRefresh)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al evaluar cumplimiento de tags: {str(e)}")


class InventoryHistoryRequest(BaseModel):
    subscriptionIds: Optional[List[str]] = None
    days: Optional[int] = 90



@router.post("/api/inventory/history")
def inventory_history(history: HistoryDep, req: InventoryHistoryRequest):
    """
    Evolucion historica de los KPIs de gobernanza para el scope indicado.

    La serie se acumula desde la primera vez que se consulta el resumen; no
    reconstruye el pasado, asi que al principio informa que aun no hay
    suficientes puntos para dibujar una tendencia.
    """
    try:
        return history.get_series(
            subscription_ids=req.subscriptionIds or [],
            days=req.days or 90,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/api/inventory/manual-creations")
def inventory_manual_creations(inventory: InventoryDep, req: SubscriptionSummaryRequest):
    """
    Recursos creados a mano, con evidencia del historial de cambios de Azure.

    A diferencia del KPI de candidatos a Shadow IT —que solo puede constatar que
    nadie declaro el recurso—, esto nombra a la identidad que lo creo. La
    respuesta incluye la ventana observada porque Azure conserva esos eventos
    unos catorce dias: es evidencia de lo reciente, nunca del historico.
    """
    try:
        return inventory.get_manual_creations(req.subscriptionIds or [])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/inventory/export")
def inventory_export(inventory: InventoryDep, req: InventoryResourcesRequest):
    """Exports inventory as CSV. Generates in-memory, no database required."""
    from fastapi.responses import StreamingResponse
    import io
    try:
        filters = req.filters.model_dump() if req.filters else {}
        csv_content = inventory.export_csv(req.subscriptionIds, filters)
        
        stream = io.BytesIO(csv_content.encode("utf-8-sig"))
        from datetime import datetime
        filename = f"Inventario_Gobernanza_Azure_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return StreamingResponse(
            stream,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al exportar CSV: {str(e)}")


# =============================================================================
# Kubernetes SRE Agent — Endpoints
# =============================================================================



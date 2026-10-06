
from fastapi import APIRouter, HTTPException
from typing import Optional
from app.schemas.inventory import *
from app.schemas.k8s import *
from app.schemas.requests import *
from app.core.container import get_services, cost_warm_status


router = APIRouter(tags=['finops'])

@router.get("/api/finops/details")
def get_finops_details():
    """Legacy endpoint kept for backwards compatibility. Returns basic orphan counts."""
    try:
        disks = get_services()[0].query_azure_resource_graph(
            "resources | where type =~ 'microsoft.compute/disks' and properties.diskState =~ 'Unattached' "
            "| project name, resourceGroup, sizeGB = toint(properties.diskSizeGB), location"
        ) or []
        ips = get_services()[0].query_azure_resource_graph(
            "resources | where type =~ 'microsoft.network/publicipaddresses' and isnull(properties.ipConfiguration) "
            "| project name, resourceGroup, ipAddress = properties.ipAddress, location"
        ) or []
        return {"unattached_disks": disks, "unassociated_ips": ips}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/finops/costs")
def get_cost_overview(subscriptions: Optional[str] = None):
    """
    Vista global de costos: totales, tendencia diaria, desgloses y ranking.

    Es la entrada del modulo de FinOps: cuanto se gasta y en que, antes que el
    ahorro. Solo facturacion real; las suscripciones sin cobertura se declaran.
    """
    try:
        subs_list = subscriptions.split(",") if subscriptions else None
        return get_services()[10].build(subs_list)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/finops/report")
def get_finops_report(subscriptions: Optional[str] = None):
    """
    Reporte integral de FinOps con gasto facturado real.

    Las cifras provienen de Azure Cost Management y Azure Monitor. Cuando esas
    APIs no estan disponibles el reporte sigue respondiendo, pero marca sus
    numeros como estimados en el bloque `cost_data` en vez de presentarlos como
    facturacion.
    """
    try:
        subs_list = subscriptions.split(",") if subscriptions else None
        return get_services()[5].build_report(subs_list)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/api/finops/warm-status")
def finops_warm_status():
    """Estado de la precarga de costos en segundo plano."""
    return cost_warm_status




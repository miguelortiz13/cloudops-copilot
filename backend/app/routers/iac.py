
from fastapi import APIRouter, HTTPException
from app.schemas.inventory import *
from app.schemas.k8s import *
from app.schemas.requests import *
from app.core.authz import Usuario, requiere
from app.core.deps import AzureDep, InventoryDep
from app.llm.limits import exigir_cupo


router = APIRouter(tags=['iac'])

@router.post("/api/iac/terraform-coverage")
def terraform_coverage(inventory: InventoryDep, req: SubscriptionSummaryRequest):
    """
    Cobertura real de Terraform, leida de los estados.

    Sustituye al porcentaje de recursos con tag de IaC —que mide cuantos equipos
    etiquetan, no cuanta infraestructura esta codificada— por el cruce del
    inventario con los ids que aparecen en los estados de Terraform.
    """
    try:
        return inventory.get_terraform_coverage(
            req.subscriptionIds or [], force_refresh=req.forceRefresh
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/iac/generate")
def generate_iac_files(azure: AzureDep, req: IaCGenerateRequest, usuario: Usuario = requiere("lector")):
    """Generates Terraform files (main.tf, providers.tf, backend.hcl, etc.) for a manual resource."""
    exigir_cupo(usuario.actor)
    try:
        from app.agents.iac_generator import IaCManager
        iac_mgr = IaCManager(azure)
        files = iac_mgr.generate_iac_files(
            resource_id=req.resource_id,
            environment=req.environment,
            domain=req.domain,
            usuario=usuario.actor,
        )
        return files
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ======================================================================
# INVENTORY & GOVERNANCE MODULE v2.0 ENDPOINTS
# ======================================================================



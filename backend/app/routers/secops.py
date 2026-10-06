
from fastapi import APIRouter, HTTPException
from typing import Optional
from app.schemas.inventory import *
from app.schemas.k8s import *
from app.schemas.requests import *
from app.core.container import get_services


router = APIRouter(tags=['secops'])

@router.get("/api/secops/details")
def get_secops_details():
    """Legacy endpoint kept for backwards compatibility. Returns basic NSG/failed counts."""
    try:
        nsgs = get_services()[0].query_azure_resource_graph(
            "resources | where type =~ 'microsoft.network/networksecuritygroups' "
            "| mv-expand rules=properties.securityRules "
            "| where rules.properties.direction =~ 'Inbound' and rules.properties.access =~ 'Allow' "
            "  and (rules.properties.destinationPortRange in ('22', '3389', '*') "
            "       or rules.properties.destinationPortRanges has '22' "
            "       or rules.properties.destinationPortRanges has '3389') "
            "  and (rules.properties.sourceAddressPrefix in ('*', '0.0.0.0/0', 'Internet') "
            "       or rules.properties.sourceAddressPrefixes has '*' "
            "       or rules.properties.sourceAddressPrefixes has 'Internet') "
            "| project name, resourceGroup, port = rules.properties.destinationPortRange, "
            "          source = rules.properties.sourceAddressPrefix, ruleName = rules.name"
        ) or []
        failed = get_services()[0].query_azure_resource_graph(
            "resources | where properties.provisioningState =~ 'Failed' "
            "| project name, type, resourceGroup, location"
        ) or []
        return {"exposed_nsgs": nsgs, "failed_resources": failed}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/api/secops/exposure")
def get_secops_exposure(subscriptions: Optional[str] = None):
    """
    Hallazgos de seguridad priorizados por severidad y por gasto expuesto.

    SecOps y FinOps no se conocian: el panel ordenaba por severidad y ahi
    terminaba, de modo que un storage publico de 2.000 USD al mes y uno de 3 USD
    se veian igual de urgentes. Aqui la severidad manda y el dinero desempata.
    """
    try:
        subs_list = [s.strip() for s in subscriptions.split(",")] if subscriptions else []
        return get_services()[8].build_report(subs_list)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/secops/report")
def get_secops_report(subscriptions: Optional[str] = None):
    """
    Reporte de seguridad con hallazgos clasificados por severidad.

    Las consultas se acotaron a la condicion que implica exposicion real: antes
    se reportaba el 96% de las cuentas de almacenamiento y el 100% de los Key
    Vaults del tenant, lo que hacia inservible el panel.
    """
    try:
        subs_list = subscriptions.split(",") if subscriptions else None
        return get_services()[6].build_report(subs_list)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




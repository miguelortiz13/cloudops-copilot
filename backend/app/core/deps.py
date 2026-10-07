"""
Dependencias de FastAPI para los routers.

Cada endpoint declara los servicios que usa como parametros tipados:

    @router.get("/api/finops/costs")
    def costos(cost_overview: CostOverviewDep): ...

Asi el contrato queda en la firma (y en la documentacion del API) en vez de en
un indice de tupla, y las pruebas sustituyen un servicio con
`app.dependency_overrides[deps.services]` sin tocar Azure.
"""

from typing import Annotated

from fastapi import Depends

from app.agents.azure_agent import AzureInventoryAgent
from app.core.container import Services, get_services
from app.providers.azure import AzureClient
from app.services.cost_overview_service import CostOverviewService
from app.services.cost_service import CostService
from app.services.finops_service import FinOpsService
from app.services.history_service import HistoryService
from app.services.inventory_service import InventoryService
from app.services.k8s_service import K8sService
from app.services.metrics_service import MetricsService
from app.services.risk_service import RiskService
from app.services.secops_service import SecOpsService
from app.services.tfstate_service import TfStateService


def services() -> Services:
    """Punto unico de sustitucion en pruebas."""
    return get_services()


ServicesDep = Annotated[Services, Depends(services)]


def _azure(s: ServicesDep) -> AzureClient:
    return s.azure


def _agent(s: ServicesDep) -> AzureInventoryAgent:
    return s.agent


def _inventory(s: ServicesDep) -> InventoryService:
    return s.inventory


def _history(s: ServicesDep) -> HistoryService:
    return s.history


def _cost(s: ServicesDep) -> CostService:
    return s.cost


def _metrics(s: ServicesDep) -> MetricsService:
    return s.metrics


def _finops(s: ServicesDep) -> FinOpsService:
    return s.finops


def _secops(s: ServicesDep) -> SecOpsService:
    return s.secops


def _k8s(s: ServicesDep) -> K8sService:
    return s.k8s


def _risk(s: ServicesDep) -> RiskService:
    return s.risk


def _tfstate(s: ServicesDep) -> TfStateService:
    return s.tfstate


def _cost_overview(s: ServicesDep) -> CostOverviewService:
    return s.cost_overview


AzureDep = Annotated[AzureClient, Depends(_azure)]
AgentDep = Annotated[AzureInventoryAgent, Depends(_agent)]
InventoryDep = Annotated[InventoryService, Depends(_inventory)]
HistoryDep = Annotated[HistoryService, Depends(_history)]
CostDep = Annotated[CostService, Depends(_cost)]
MetricsDep = Annotated[MetricsService, Depends(_metrics)]
FinOpsDep = Annotated[FinOpsService, Depends(_finops)]
SecOpsDep = Annotated[SecOpsService, Depends(_secops)]
K8sDep = Annotated[K8sService, Depends(_k8s)]
RiskDep = Annotated[RiskService, Depends(_risk)]
TfStateDep = Annotated[TfStateService, Depends(_tfstate)]
CostOverviewDep = Annotated[CostOverviewService, Depends(_cost_overview)]

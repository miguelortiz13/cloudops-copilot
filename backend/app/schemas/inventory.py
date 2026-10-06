"""
Pydantic v2 models for the inventory module.
"""
from typing import Optional, List, Dict
from pydantic import BaseModel, Field

from app.core import config

class MandatoryTagsResult(BaseModel):
    """Result of evaluating mandatory tags on a resource."""
    totalRequired: int = Field(default=6, description="Total number of required tags")
    present: int = Field(description="Number of required tags present")
    missing: List[str] = Field(description="List of missing required tags")
    compliancePercentage: float = Field(description="Percentage of mandatory tags present")
    isCompliant: bool = Field(description="Whether the resource has all mandatory tags")

class GovernanceInfo(BaseModel):
    """Governance information for a resource."""
    hasOwnerCandidate: bool = Field(default=False)
    ownerCandidate: Optional[str] = Field(default=None)
    isProduction: bool = Field(default=False)
    isNonProduction: bool = Field(default=False)
    isShadowItCandidate: bool = Field(default=False)
    shadowItReason: Optional[str] = Field(default=None)
    dataCompletenessScore: float = Field(default=0.0)

class ResourceInventoryItem(BaseModel):
    """A detailed representation of an inventory resource."""
    id: str
    name: str
    type: str
    typeDisplayName: Optional[str] = Field(default=None)
    subscriptionId: str
    subscriptionName: str = Field(default="")
    resourceGroup: str
    location: str
    kind: Optional[str] = Field(default=None)
    skuName: Optional[str] = Field(default=None)
    skuTier: Optional[str] = Field(default=None)
    provisioningState: Optional[str] = Field(default=None)
    createdTime: Optional[str] = Field(default=None)
    changedTime: Optional[str] = Field(default=None)
    managedBy: Optional[str] = Field(default=None)
    tags: Dict[str, str] = Field(default_factory=dict)
    environment: Optional[str] = Field(default=None)
    customer: Optional[str] = Field(default=None)
    tenant: Optional[str] = Field(default=None)
    platform: Optional[str] = Field(default=None)
    product: Optional[str] = Field(default=None)
    suite: Optional[str] = Field(default=None)
    mandatoryTags: MandatoryTagsResult = Field(
        default_factory=lambda: MandatoryTagsResult(present=0, missing=[], compliancePercentage=0.0, isCompliant=False)
    )
    governance: GovernanceInfo = Field(default_factory=GovernanceInfo)

class InventoryFilters(BaseModel):
    """Filters to apply when querying inventory resources."""
    resourceGroups: List[str] = Field(default_factory=list)
    types: List[str] = Field(default_factory=list)
    locations: List[str] = Field(default_factory=list)
    environments: List[str] = Field(default_factory=list)
    missingTags: List[str] = Field(default_factory=list)
    onlyNonCompliant: bool = Field(default=False)
    onlyShadowItCandidates: bool = Field(default=False)
    search: str = Field(default="")

class InventoryResourcesRequest(BaseModel):
    """Request payload to query inventory resources."""
    subscriptionIds: List[str] = Field(default_factory=list)
    filters: InventoryFilters = Field(default_factory=InventoryFilters)
    page: int = Field(default=1)
    pageSize: int = Field(default=100)
    forceRefresh: bool = Field(default=False)

class InventoryResourcesResponse(BaseModel):
    """Response payload containing a paginated list of inventory resources."""
    items: List[ResourceInventoryItem] = Field(default_factory=list)
    total: int = Field(default=0)
    page: int = Field(default=1)
    pageSize: int = Field(default=100)
    lastUpdated: Optional[str] = Field(default=None)
    partialSuccess: bool = Field(default=False)
    warnings: List[str] = Field(default_factory=list)

class SubscriptionInfo(BaseModel):
    """Information about an Azure subscription."""
    subscriptionId: str
    displayName: str
    state: str = Field(default="Enabled")
    tenantId: Optional[str] = Field(default=None)

class SubscriptionSummaryRequest(BaseModel):
    """Request payload to query subscription summaries."""
    subscriptionIds: List[str] = Field(default_factory=list)
    # Omitir el campo mantiene el comportamiento cacheado de siempre.
    forceRefresh: bool = False

class DistributionItem(BaseModel):
    """An item representing a distribution metric."""
    key: str
    count: int
    percentage: float = Field(default=0.0)

class InventorySummaryResponse(BaseModel):
    """Response payload containing an overall summary of the inventory."""
    totalResources: int = Field(default=0)
    totalSubscriptions: int = Field(default=0)
    totalResourceGroups: int = Field(default=0)
    totalRegions: int = Field(default=0)
    tagCompliancePercentage: float = Field(default=0.0)
    nonCompliantResources: int = Field(default=0)
    shadowItCandidates: int = Field(default=0)
    resourcesWithoutOwnerCandidate: int = Field(default=0)
    productionResources: int = Field(default=0)
    nonProductionResources: int = Field(default=0)
    bySubscription: List[DistributionItem] = Field(default_factory=list)
    byResourceType: List[DistributionItem] = Field(default_factory=list)
    byRegion: List[DistributionItem] = Field(default_factory=list)
    byEnvironment: List[DistributionItem] = Field(default_factory=list)
    lastUpdated: Optional[str] = Field(default=None)
    partialSuccess: bool = Field(default=False)
    warnings: List[str] = Field(default_factory=list)

class TagComplianceMatrixItem(BaseModel):
    """An item representing tag compliance metrics."""
    tag: str
    present: int = Field(default=0)
    missing: int = Field(default=0)
    compliancePercentage: float = Field(default=0.0)

class TagComplianceResponse(BaseModel):
    """Response payload detailing tag compliance."""
    requiredTags: List[str] = Field(
        default_factory=lambda: list(config.MANDATORY_TAGS)
    )
    matrix: List[TagComplianceMatrixItem] = Field(default_factory=list)
    totalResources: int = Field(default=0)
    overallCompliancePercentage: float = Field(default=0.0)
    lastUpdated: Optional[str] = Field(default=None)
    partialSuccess: bool = Field(default=False)
    warnings: List[str] = Field(default_factory=list)

class InventoryHealthResponse(BaseModel):
    """Health and status of the inventory module."""
    status: str = Field(default="ok")
    azureConnected: bool = Field(default=False)
    credentialsConfigured: bool = Field(default=False)
    timestamp: str = Field(default="")
    cacheEnabled: bool = Field(default=True)
    cacheTtlSeconds: int = Field(default=300)
    version: str = Field(default="2.0.0")

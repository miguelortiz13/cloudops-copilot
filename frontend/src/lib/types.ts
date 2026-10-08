/** Contratos del API. Reflejan las respuestas del backend (app/routers). */

export type Role = 'lector' | 'operador' | 'administrador';

/** /api/me: el usuario y su rol (app roles de Entra ID). */
export interface Me {
  name: string;
  upn: string;
  role: Role;
  permissions: Record<Role, boolean>;
  auth_enabled: boolean;
  /** De dónde sale el rol: grupo de seguridad, app role o por defecto. */
  role_source?: 'grupo' | 'app_role' | 'por_defecto' | 'sin_autenticacion';
}

export interface Subscription {
  subscriptionId: string;
  displayName: string;
  state: string;
}

export interface Distribution {
  key: string;
  count: number;
  percentage: number;
}

export interface InventorySummary {
  totalResources: number;
  totalSubscriptions: number;
  totalResourceGroups: number;
  totalRegions: number;
  tagCompliancePercentage: number;
  nonCompliantResources: number;
  shadowItCandidates: number;
  resourcesWithoutOwnerCandidate: number;
  productionResources: number;
  nonProductionResources: number;
  bySubscription: Distribution[];
  byResourceType: Distribution[];
  byRegion: Distribution[];
  byEnvironment: Distribution[];
  lastUpdated?: string;
  partialSuccess: boolean;
  warnings: string[];
}

export interface TagCompliance {
  requiredTags: string[];
  matrix: { tag: string; present: number; missing: number; compliancePercentage: number }[];
  totalResources: number;
  overallCompliancePercentage: number;
  warnings: string[];
}

export interface InventoryResource {
  id: string;
  name: string;
  type: string;
  typeDisplayName?: string;
  subscriptionId: string;
  subscriptionName: string;
  resourceGroup: string;
  location: string;
  kind?: string;
  skuName?: string;
  skuTier?: string;
  provisioningState?: string;
  createdTime?: string;
  changedTime?: string;
  managedBy?: string;
  tags: Record<string, string>;
  tagValues?: Record<string, string | null>;
  environment?: string;
  mandatoryTags: {
    totalRequired: number;
    present: number;
    missing: string[];
    compliancePercentage: number;
    isCompliant: boolean;
  };
  governance: {
    hasOwnerCandidate: boolean;
    ownerCandidate?: string;
    isProduction: boolean;
    isNonProduction: boolean;
    isShadowItCandidate: boolean;
    shadowItReason?: string;
    dataCompletenessScore: number;
  };
}

export interface InventoryPage {
  items: InventoryResource[];
  total: number;
  page: number;
  pageSize: number;
  warnings: string[];
}

export interface HistoryPoint {
  date: string;
  totalResources?: number;
  nonCompliantResources?: number;
  tagCompliancePercentage?: number;
  shadowItCandidates?: number;
  resourcesWithoutOwnerCandidate?: number;
}

export interface HistorySeries {
  points: HistoryPoint[];
  available: boolean;
  pointCount?: number;
  deltas: Record<string, number>;
}

// ---------------------------------------------------------------- FinOps

export interface CostGroup {
  key: string;
  cost: number;
  share: number;
}

export interface CostResource {
  id: string;
  name: string;
  type: string;
  service: string;
  resourceGroup: string;
  subscriptionId: string;
  subscriptionName: string;
  location: string;
  deleted: boolean;
  tags: Record<string, string | null>;
  cost: number;
  share: number;
}

export interface CostOverview {
  basis: 'actual' | 'partial' | 'unavailable';
  message: string;
  currency: string;
  window_days: number;
  coverage: {
    covered: string[];
    denied: string[];
    failed: string[];
    covered_names: string[];
    uncovered_names: string[];
  };
  cache_age_seconds: number;
  totals: {
    last_period: number;
    previous_period: number | null;
    delta_percentage: number | null;
    daily_average: number;
    month_to_date: number | null;
    forecast_month: number | null;
    period_days: number;
    period_start: string | null;
    period_end: string | null;
    resource_attributed: number;
    unassigned_charges: number;
    resources_with_cost: number;
    deleted_resources_with_cost: number;
  };
  daily: { date: string; cost: number }[];
  by_subscription: CostGroup[];
  by_resource_group: CostGroup[];
  by_service: CostGroup[];
  by_location: CostGroup[];
  by_tag: Record<string, CostGroup[]>;
  top_resources: CostResource[];
}

export interface OrphanResource {
  id?: string;
  name: string;
  resourceGroup: string;
  location?: string;
  sku?: string;
  sizeGB?: number;
  ipAddress?: string;
  numberOfSites?: number;
  type?: string;
  monthly_cost_usd?: number;
  cost_basis?: string;
}

export interface FinOpsReport {
  unattached_disks: OrphanResource[];
  unassociated_ips: OrphanResource[];
  orphaned_nics: OrphanResource[];
  empty_app_plans: OrphanResource[];
  old_snapshots: OrphanResource[];
  untagged_resources: OrphanResource[];
  estimated_savings_breakdown: Record<string, number>;
  savings_lifecycle?: {
    potential_savings_usd: number;
    potential_from_billing_usd?: number;
    potential_from_estimate_usd?: number;
    schedule_savings_usd?: number;
    reservation_savings_usd?: number;
    approved_savings_usd: number;
    realized_savings_usd: number;
  };
  cost_data?: { basis?: string; message?: string; currency?: string };
  insights?: {
    budgets: {
      name?: string;
      scope: string;
      current_spending: number;
      budget_limit: number;
      percentage_used: number;
      forecast?: number;
    }[];
    budgets_status?: string;
    anomalies: { title: string; description: string; recomm_action: string; severity?: string }[];
    underutilized_resources: {
      name: string;
      size: string;
      avg_cpu_percentage: number;
      monthly_cost_usd: number;
    }[];
    running_dev_vms_outside_hours: {
      name: string;
      environment: string;
      resourceGroup: string;
      saving_potential: number;
    }[];
    reservation_recommendations: {
      resource_type: string;
      sku_size: string;
      quantity_instances: number;
      savings_plan_option: string;
      estimated_savings_percentage: number;
      monthly_saving_usd: number;
    }[];
    aging_resources_no_expiration: { name: string; type: string; resourceGroup: string }[];
  };
}

export type CostPeriod = '7d' | '30d' | '90d' | 'mtd' | 'last_month';

/** /api/history/costs: costos desde la base, por periodo y con comparación. */
export interface CostHistory {
  available: boolean;
  message?: string;
  period: CostPeriod;
  label: string;
  from: string;
  to: string;
  previous_from: string;
  previous_to: string;
  previous_complete: boolean;
  currency: string;
  total: number;
  previous_total: number;
  delta_percentage: number | null;
  daily: { date: string; cost: number }[];
  by_service: CostGroup[];
  by_account: (CostGroup & { name: string })[];
  by_resource: (CostGroup & { name: string; type: string | null; group: string | null; account: string | null; deleted: boolean })[];
  by_month: { month: string; cost: number }[];
  data_from: string | null;
  data_through: string;
  collected_at: string | null;
  source?: 'cache' | 'database';
}

// ---------------------------------------------------------------- SecOps

export type Severity = 'critica' | 'alta' | 'media';

export interface Finding {
  id: string;
  name: string;
  resourceGroup?: string;
  location?: string;
  subscriptionId?: string;
  tipo: string;
  titulo: string;
  severidad: Severity;
  recomendacion?: string;
  monthly_cost_usd?: number;
  cost_basis?: 'actual' | 'unavailable' | 'not_applicable';
  port?: string;
  source?: string;
}

export interface SecOpsReport {
  findings: Finding[];
  severity_summary: Record<Severity, number>;
  attack_surface_summary: Record<string, number>;
}

export interface RiskExposure {
  findings: Finding[];
  top_exposure: {
    id: string;
    name: string;
    tipo: string;
    severidad: Severity;
    monthly_cost_usd: number;
    cost_basis: string;
    hallazgos: number;
  }[];
  totals: {
    findings: number;
    affected_resources: number;
    measured_resources: number;
    unmeasured_resources: number;
    monthly_usd_at_risk: number;
    currency: string;
  };
  coverage: { status: string; covered_count: number; uncovered_count: number; message: string };
}

export type FindingStatus = 'abierto' | 'asumido' | 'aceptado' | 'resuelto';

/** Hallazgo con ciclo de vida, desde la base (/api/findings). */
export interface ManagedFinding {
  id: number;
  rule_id: string;
  title: string;
  remediation: string | null;
  severity: Severity;
  status: FindingStatus;
  resource_uid: string;
  resource_name: string;
  resource_type: string | null;
  resource_group: string | null;
  account: string | null;
  details: Record<string, unknown>;
  owner: string | null;
  due_date: string | null;
  accepted_until: string | null;
  first_seen: string;
  last_seen: string;
  resolved_at: string | null;
}

export interface ManagedFindings {
  available: boolean;
  items: ManagedFinding[];
  by_status: Partial<Record<FindingStatus, number>>;
  collected_at: string | null;
  source?: 'cache' | 'database';
}

export interface FindingEvent {
  at: string;
  kind: 'detectado' | 'estado' | 'resuelto' | 'reabierto' | 'vencido';
  from: FindingStatus | null;
  to: FindingStatus | null;
  actor: string;
  note: string | null;
}

// ---------------------------------------------------------------- IaC

export interface TerraformCoverage {
  available: boolean;
  managed_in_inventory: number;
  total_resources: number;
  coverage_percentage: number;
  unmanaged_count: number;
  states_read: number;
  states_failed: number;
  managed_ids_total: number;
  stale_ids: number;
  states: { name: string; ok: boolean; resources: number; reason: string | null }[];
  sources_failed?: string[];
  message: string;
}

export interface ManualCreations {
  manualCreations: { id: string; name: string; type: string; createdBy: string; createdAt: string }[];
  manualCount: number;
  automatedCount: number;
  totalCreations: number;
  windowFrom: string | null;
  windowTo: string | null;
  available: boolean;
}

export type IacFile = 'main_tf' | 'providers_tf' | 'variables_tf' | 'outputs_tf' | 'terraform_tfvars' | 'backend_hcl';

export type IacResult = Record<IacFile, string> & { generation_mode: string };

// ---------------------------------------------------------------- ISO

export interface IsoAsset {
  name: string;
  resourceType: string;
  subscription?: string;
  custodio?: string;
  confidencialidad: number;
  integridad: number;
  disponibilidad: number;
  'Clasificación del activo': string;
  'puntuación del activo': number;
  'Gestión de riesgo (SI/NO)': string;
}

export interface IsoReport {
  data: IsoAsset[];
  error?: string;
  stats: {
    total_assets?: number;
    classification_distribution?: Record<string, number>;
    risk_management_distribution?: Record<string, number>;
    average_criticality_score?: number;
  };
}

export interface Snapshot {
  filename: string;
  size: number;
  created_at: string;
}

export interface SyncStatus {
  running: boolean;
  last_run: string;
  logs: string;
  error: string | null;
}

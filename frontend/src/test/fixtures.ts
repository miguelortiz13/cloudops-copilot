/**
 * Datos ficticios del API para las pruebas (Vitest y Playwright).
 *
 * Tipados contra src/lib/types.ts: si un contrato cambia, `tsc` falla aquí en
 * vez de que una prueba pase con datos que el backend ya no envía. Ningún dato
 * es real: suscripciones, nombres y usuarios son inventados (el repositorio es
 * público y las capturas de regresión visual salen de aquí).
 */
import type {
  ClassifiedAsset, ClassifiedAssets, ComplianceStatus, ConnectedAccounts, CostHistory, CostOverview, FindingEvent, FinOpsReport,
  HistorySeries, InventoryPage, InventoryResource, InventorySummary, ManagedFinding, ManagedFindings, ManualCreations,
  Me, RiskExposure, Role, SecOpsReport, Snapshot, Subscription, SyncStatus, TagCompliance, TerraformCoverage,
} from '../lib/types';

export const SUB_PROD = '00000000-0000-4000-8000-000000000001';
export const SUB_LAB = '00000000-0000-4000-8000-000000000002';
const rid = (sub: string, rg: string, type: string, name: string) =>
  `/subscriptions/${sub}/resourceGroups/${rg}/providers/${type}/${name}`;

export const subscriptions: { subscriptions: Subscription[] } = {
  subscriptions: [
    { subscriptionId: SUB_PROD, displayName: 'Producción (demo)', state: 'Enabled' },
    { subscriptionId: SUB_LAB, displayName: 'Laboratorio (demo)', state: 'Enabled' },
  ],
};

export function me(role: Role = 'administrador'): Me {
  const nivel = { lector: 0, operador: 1, administrador: 2 }[role];
  return {
    name: 'Ana Prueba',
    upn: 'ana@contoso.example',
    role,
    permissions: { lector: true, operador: nivel >= 1, administrador: nivel >= 2 },
    auth_enabled: true,
    role_source: 'grupo',
  };
}

// ---------------------------------------------------------------- inventario

export const inventorySummary: InventorySummary = {
  totalResources: 48,
  totalSubscriptions: 2,
  totalResourceGroups: 9,
  totalRegions: 2,
  tagCompliancePercentage: 72.9,
  nonCompliantResources: 13,
  shadowItCandidates: 3,
  resourcesWithoutOwnerCandidate: 11,
  productionResources: 21,
  nonProductionResources: 27,
  bySubscription: [
    { key: 'Producción (demo)', count: 21, percentage: 43.8 },
    { key: 'Laboratorio (demo)', count: 27, percentage: 56.2 },
  ],
  byResourceType: [
    { key: 'microsoft.web/sites', count: 12, percentage: 25 },
    { key: 'microsoft.storage/storageaccounts', count: 9, percentage: 18.8 },
    { key: 'microsoft.keyvault/vaults', count: 6, percentage: 12.5 },
    { key: 'microsoft.network/networksecuritygroups', count: 5, percentage: 10.4 },
    { key: 'microsoft.sql/servers', count: 3, percentage: 6.3 },
  ],
  byRegion: [
    { key: 'eastus2', count: 36, percentage: 75 },
    { key: 'centralus', count: 12, percentage: 25 },
  ],
  byEnvironment: [
    { key: 'prod', count: 21, percentage: 43.8 },
    { key: 'dev', count: 19, percentage: 39.6 },
    { key: 'Sin definir', count: 8, percentage: 16.6 },
  ],
  lastUpdated: '2026-10-10T11:02:00Z',
  partialSuccess: false,
  warnings: [],
};

export const tagCompliance: TagCompliance = {
  requiredTags: ['Environment', 'Owner', 'CostCenter'],
  matrix: [
    { tag: 'Environment', present: 40, missing: 8, compliancePercentage: 83.3 },
    { tag: 'Owner', present: 37, missing: 11, compliancePercentage: 77.1 },
    { tag: 'CostCenter', present: 28, missing: 20, compliancePercentage: 58.3 },
  ],
  totalResources: 48,
  overallCompliancePercentage: 72.9,
  warnings: [],
};

export const inventoryHistory: HistorySeries = {
  available: true,
  pointCount: 5,
  points: [
    { date: '2026-10-06', totalResources: 44, tagCompliancePercentage: 68.2, nonCompliantResources: 14, shadowItCandidates: 4 },
    { date: '2026-10-07', totalResources: 45, tagCompliancePercentage: 68.9, nonCompliantResources: 14, shadowItCandidates: 4 },
    { date: '2026-10-08', totalResources: 46, tagCompliancePercentage: 70.1, nonCompliantResources: 14, shadowItCandidates: 3 },
    { date: '2026-10-09', totalResources: 48, tagCompliancePercentage: 72.0, nonCompliantResources: 13, shadowItCandidates: 3 },
    { date: '2026-10-10', totalResources: 48, tagCompliancePercentage: 72.9, nonCompliantResources: 13, shadowItCandidates: 3 },
  ],
  deltas: { totalResources: 4, tagCompliancePercentage: 4.7 },
};

function recurso(nombre: string, tipo: string, rg: string, sub: string, env: string | undefined, owner?: string): InventoryResource {
  const tags: Record<string, string> = {};
  if (env) tags.Environment = env;
  if (owner) tags.Owner = owner;
  const faltan = ['Environment', 'Owner', 'CostCenter'].filter((t) => !tags[t]);
  return {
    id: rid(sub, rg, tipo, nombre),
    name: nombre,
    type: tipo.toLowerCase(),
    subscriptionId: sub,
    subscriptionName: sub === SUB_PROD ? 'Producción (demo)' : 'Laboratorio (demo)',
    resourceGroup: rg,
    location: 'eastus2',
    provisioningState: 'Succeeded',
    createdTime: '2026-08-14T15:20:00Z',
    tags,
    environment: env,
    mandatoryTags: {
      totalRequired: 3, present: 3 - faltan.length, missing: faltan,
      compliancePercentage: Math.round(((3 - faltan.length) / 3) * 1000) / 10, isCompliant: faltan.length === 0,
    },
    governance: {
      hasOwnerCandidate: Boolean(owner), ownerCandidate: owner, isProduction: env === 'prod',
      isNonProduction: env === 'dev', isShadowItCandidate: !env && !owner,
      shadowItReason: !env && !owner ? 'sin IaC, sin custodio y sin tags obligatorias' : undefined,
      dataCompletenessScore: (3 - faltan.length) / 3,
    },
  };
}

export const resources: InventoryResource[] = [
  recurso('kv-pagos-prod', 'Microsoft.KeyVault/vaults', 'rg-pagos-prod', SUB_PROD, 'prod', 'equipo-pagos'),
  recurso('sql-pagos-prod', 'Microsoft.Sql/servers', 'rg-pagos-prod', SUB_PROD, 'prod', 'equipo-pagos'),
  recurso('app-pagos-prod', 'Microsoft.Web/sites', 'rg-pagos-prod', SUB_PROD, 'prod', 'equipo-pagos'),
  recurso('nsg-pagos-prod', 'Microsoft.Network/networkSecurityGroups', 'rg-pagos-prod', SUB_PROD, 'prod'),
  recurso('stwebdev01', 'Microsoft.Storage/storageAccounts', 'rg-web-dev', SUB_LAB, 'dev', 'equipo-web'),
  recurso('app-web-dev', 'Microsoft.Web/sites', 'rg-web-dev', SUB_LAB, 'dev'),
  recurso('vm-pruebas', 'Microsoft.Compute/virtualMachines', 'rg-lab', SUB_LAB, undefined),
];

export const inventoryPage: InventoryPage = { items: resources, total: resources.length, page: 1, pageSize: 25, warnings: [] };

// ---------------------------------------------------------------- costos

const diario = Array.from({ length: 60 }, (_, i) => {
  const d = new Date(Date.UTC(2026, 7, 12 + i));
  // Gasto estable con ciclo semanal, sin aleatoriedad: las capturas no cambian.
  const cost = 3.1 + ((i % 7) - 3) * 0.18 + (i > 45 ? 0.6 : 0);
  return { date: d.toISOString().slice(0, 10), cost: Math.round(cost * 100) / 100 };
});

export const costOverview: CostOverview = {
  basis: 'actual',
  message: 'Costo real de Cost Management para todas las suscripciones.',
  currency: 'USD',
  window_days: 30,
  coverage: {
    covered: [SUB_PROD, SUB_LAB], denied: [], failed: [],
    covered_names: ['Producción (demo)', 'Laboratorio (demo)'], uncovered_names: [],
  },
  cache_age_seconds: 930,
  totals: {
    last_period: 104.2, previous_period: 92.6, delta_percentage: 12.5, daily_average: 3.47,
    month_to_date: 36.8, forecast_month: 112.4, period_days: 30, period_start: '2026-09-11', period_end: '2026-10-10',
    resource_attributed: 101.9, unassigned_charges: 2.3, resources_with_cost: 17, deleted_resources_with_cost: 1,
  },
  daily: diario,
  by_subscription: [{ key: 'Producción (demo)', cost: 71.4, share: 68.5 }, { key: 'Laboratorio (demo)', cost: 32.8, share: 31.5 }],
  by_resource_group: [
    { key: 'rg-pagos-prod', cost: 64.1, share: 61.5 }, { key: 'rg-web-dev', cost: 21.7, share: 20.8 },
    { key: 'rg-lab', cost: 11.1, share: 10.7 }, { key: 'rg-compartido', cost: 7.3, share: 7 },
  ],
  by_service: [
    { key: 'Azure App Service', cost: 38.2, share: 36.7 }, { key: 'SQL Database', cost: 27.5, share: 26.4 },
    { key: 'Storage', cost: 14.9, share: 14.3 }, { key: 'Virtual Machines', cost: 12.4, share: 11.9 },
    { key: 'Key Vault', cost: 4.1, share: 3.9 }, { key: 'Otros', cost: 7.1, share: 6.8 },
  ],
  by_location: [{ key: 'eastus2', cost: 88.3, share: 84.7 }, { key: 'centralus', cost: 15.9, share: 15.3 }],
  by_tag: {
    Environment: [{ key: 'prod', cost: 71.4, share: 68.5 }, { key: 'dev', cost: 24.6, share: 23.6 }, { key: '(sin tag)', cost: 8.2, share: 7.9 }],
  },
  top_resources: resources.slice(0, 5).map((r, i) => ({
    id: r.id, name: r.name, type: r.type, service: ['Key Vault', 'SQL Database', 'Azure App Service', 'Virtual Network', 'Storage'][i],
    resourceGroup: r.resourceGroup, subscriptionId: r.subscriptionId, subscriptionName: r.subscriptionName,
    location: r.location, deleted: false, tags: r.tags, cost: [4.1, 27.5, 24.3, 0.4, 9.8][i], share: [3.9, 26.4, 23.3, 0.4, 9.4][i],
  })),
};

export const finopsReport: FinOpsReport = {
  unattached_disks: [{ id: rid(SUB_LAB, 'rg-lab', 'Microsoft.Compute/disks', 'disk-huerfano-01'), name: 'disk-huerfano-01', resourceGroup: 'rg-lab', sizeGB: 128, sku: 'StandardSSD_LRS', monthly_cost_usd: 9.6, cost_basis: 'actual' }],
  unassociated_ips: [{ name: 'pip-sin-uso', resourceGroup: 'rg-lab', ipAddress: '203.0.113.10', monthly_cost_usd: 3.65, cost_basis: 'actual' }],
  orphaned_nics: [],
  empty_app_plans: [],
  old_snapshots: [],
  untagged_resources: [{ name: 'vm-pruebas', resourceGroup: 'rg-lab', type: 'microsoft.compute/virtualmachines' }],
  estimated_savings_breakdown: { unattached_disks: 9.6, unassociated_ips: 3.65 },
  savings_lifecycle: { potential_savings_usd: 13.25, approved_savings_usd: 0, realized_savings_usd: 0 },
  cost_data: { basis: 'actual', currency: 'USD' },
  insights: {
    budgets: [{ name: 'presupuesto-lab', scope: 'Laboratorio (demo)', current_spending: 32.8, budget_limit: 50, percentage_used: 65.6, forecast: 44.1 }],
    anomalies: [],
    underutilized_resources: [],
    running_dev_vms_outside_hours: [],
    reservation_recommendations: [],
    aging_resources_no_expiration: [],
  },
};

export function costHistory(period: CostHistory['period'] = '30d'): CostHistory {
  return {
    available: true, period, label: 'Últimos 30 días', from: '2026-09-11', to: '2026-10-10',
    previous_from: '2026-08-12', previous_to: '2026-09-10', previous_complete: true, currency: 'USD',
    total: 104.2, previous_total: 92.6, delta_percentage: 12.5, daily: diario.slice(30),
    by_service: costOverview.by_service,
    by_account: [{ key: `azure:sub/${SUB_PROD}`, name: 'Producción (demo)', cost: 71.4, share: 68.5 }, { key: `azure:sub/${SUB_LAB}`, name: 'Laboratorio (demo)', cost: 32.8, share: 31.5 }],
    by_resource: [
      { key: 'r1', name: 'sql-pagos-prod', type: 'microsoft.sql/servers', group: 'rg-pagos-prod', account: 'Producción (demo)', deleted: false, cost: 27.5, share: 26.4 },
      { key: 'r2', name: 'app-pagos-prod', type: 'microsoft.web/sites', group: 'rg-pagos-prod', account: 'Producción (demo)', deleted: false, cost: 24.3, share: 23.3 },
    ],
    by_month: [{ month: '2026-08', cost: 88.4 }, { month: '2026-09', cost: 97.1 }, { month: '2026-10', cost: 36.8 }],
    data_from: '2025-10-11', data_through: '2026-10-09', collected_at: '2026-10-10T06:03:00Z', source: 'cache',
  };
}

// ---------------------------------------------------------------- seguridad

const kv = rid(SUB_PROD, 'rg-pagos-prod', 'Microsoft.KeyVault/vaults', 'kv-pagos-prod');
const nsg = rid(SUB_PROD, 'rg-pagos-prod', 'Microsoft.Network/networkSecurityGroups', 'nsg-pagos-prod');
const st = rid(SUB_LAB, 'rg-web-dev', 'Microsoft.Storage/storageAccounts', 'stwebdev01');

export const secopsReport: SecOpsReport = {
  findings: [
    { id: nsg, name: 'nsg-pagos-prod', resourceGroup: 'rg-pagos-prod', tipo: 'nsg', titulo: 'Puerto de administración abierto a internet', severidad: 'critica', port: '22', source: '*', recomendacion: 'Restringir el origen a rangos corporativos o usar Azure Bastion / Just-In-Time.' },
    { id: kv, name: 'kv-pagos-prod', resourceGroup: 'rg-pagos-prod', tipo: 'keyvault', titulo: 'Key Vault alcanzable desde red pública', severidad: 'alta', recomendacion: 'Añadir private endpoint o limitar networkAcls a redes conocidas.' },
    { id: st, name: 'stwebdev01', resourceGroup: 'rg-web-dev', tipo: 'storage', titulo: 'Cuenta de almacenamiento con blobs públicos', severidad: 'alta', recomendacion: 'Deshabilitar allowBlobPublicAccess o restringir con reglas de red.' },
  ],
  severity_summary: { critica: 1, alta: 2, media: 0 },
  attack_surface_summary: { exposed_nsg_rules: 1, public_storage_accounts: 1, exposed_keyvaults: 1, active_public_ips: 2, failed_resources: 0 },
};

export const riskExposure: RiskExposure = {
  findings: secopsReport.findings.map((f, i) => ({ ...f, monthly_cost_usd: [0.4, 4.1, 9.8][i], cost_basis: 'actual' as const })),
  top_exposure: [
    { id: st, name: 'stwebdev01', tipo: 'storage', severidad: 'alta', monthly_cost_usd: 9.8, cost_basis: 'actual', hallazgos: 1 },
    { id: kv, name: 'kv-pagos-prod', tipo: 'keyvault', severidad: 'alta', monthly_cost_usd: 4.1, cost_basis: 'actual', hallazgos: 1 },
  ],
  totals: { findings: 3, affected_resources: 3, measured_resources: 3, unmeasured_resources: 0, monthly_usd_at_risk: 14.3, currency: 'USD' },
  coverage: { status: 'complete', covered_count: 2, uncovered_count: 0, message: '' },
};

const CIS = 'cis-azure-2.0.0';
const ISO = 'iso-27001-2022';

function hallazgo(id: number, extra: Partial<ManagedFinding> & Pick<ManagedFinding, 'rule_id' | 'title' | 'severity' | 'resource_name'>): ManagedFinding {
  return {
    id, remediation: 'Corregir la configuración del recurso.', controls: {}, status: 'abierto',
    resource_uid: `azure:/x/${extra.resource_name}`, resource_type: null, resource_group: 'rg-pagos-prod',
    account: 'Producción (demo)', details: {}, owner: null, due_date: null, accepted_until: null,
    first_seen: '2026-10-08T06:02:00Z', last_seen: '2026-10-10T06:02:00Z', resolved_at: null, ...extra,
  };
}

export function managedFindings(): ManagedFindings {
  const items = [
    hallazgo(1, { rule_id: 'network.admin-port-open', title: 'Puerto de administración abierto a internet', severity: 'critica', resource_name: 'nsg-pagos-prod',
      resource_type: 'microsoft.network/networksecuritygroups', details: { ruleName: 'allow-ssh', port: '22', source: '*', asociado: true },
      controls: { [CIS]: [{ control: '6.1', match: 'directa' }, { control: '6.2', match: 'directa' }], [ISO]: [{ control: 'A.8.20', match: 'directa' }] } }),
    hallazgo(2, { rule_id: 'secrets.vault-public-network', title: 'Key Vault alcanzable desde red pública', severity: 'alta', resource_name: 'kv-pagos-prod',
      resource_type: 'microsoft.keyvault/vaults', controls: { [CIS]: [{ control: '8.7', match: 'directa' }], [ISO]: [{ control: 'A.8.24', match: 'parcial' }] } }),
    hallazgo(3, { rule_id: 'storage.public-blob-access', title: 'Cuenta de almacenamiento con blobs públicos', severity: 'alta', resource_name: 'stwebdev01',
      resource_group: 'rg-web-dev', account: 'Laboratorio (demo)', status: 'aceptado', accepted_until: '2026-12-31', owner: 'equipo-web' }),
    hallazgo(4, { rule_id: 'web.https-not-enforced', title: 'App Service sin HTTPS obligatorio', severity: 'alta', resource_name: 'app-viejo',
      status: 'resuelto', resolved_at: '2026-10-09T06:02:00Z' }),
  ];
  return { available: true, items, by_status: { abierto: 2, aceptado: 1, resuelto: 1 }, collected_at: '2026-10-10T06:03:00Z', source: 'cache' };
}

export const findingEvents: FindingEvent[] = [
  { at: '2026-10-08T06:02:00Z', kind: 'detectado', from: null, to: 'abierto', actor: 'recolector', note: null },
];

// ---------------------------------------------------------------- IaC y reportes

export const terraformCoverage: TerraformCoverage = {
  available: true, managed_in_inventory: 19, total_resources: 48, coverage_percentage: 39.6, unmanaged_count: 29,
  states_read: 2, states_failed: 0, managed_ids_total: 21, stale_ids: 2,
  states: [{ name: 'pagos/prod.tfstate', ok: true, resources: 14, reason: null }, { name: 'web/dev.tfstate', ok: true, resources: 7, reason: null }],
  message: '',
};

export const manualCreations: ManualCreations = {
  manualCreations: [{ id: rid(SUB_LAB, 'rg-lab', 'Microsoft.Compute/virtualMachines', 'vm-pruebas'), name: 'vm-pruebas', type: 'microsoft.compute/virtualmachines', createdBy: 'luis@contoso.example', createdAt: '2026-10-02T14:11:00Z' }],
  manualCount: 1, automatedCount: 6, totalCreations: 7, windowFrom: '2026-09-26', windowTo: '2026-10-10', available: true,
};

export const snapshots: Snapshot[] = [{ filename: 'inventario-2026-10-05.xlsx', size: 48211, created_at: '2026-10-05T06:00:00Z' }];
export const syncStatus: SyncStatus = { running: false, last_run: '2026-10-05T06:00:00Z', logs: '', error: null };

// ---------------------------------------------------------------- cumplimiento

export function complianceStatus(): ComplianceStatus {
  const regla = (id: string, title: string, active: number, accepted = 0) => ({ kind: 'rule' as const, rule_id: id, title, match: 'directa' as const, status: active ? 'no_cumple' as const : accepted ? 'riesgo_aceptado' as const : 'cumple' as const, active, accepted });
  return {
    available: true,
    evaluated_at: '2026-10-10T06:03:00Z',
    failed_rules: ['web.https-not-enforced'],
    source: 'cache',
    frameworks: [
      {
        id: CIS, name: 'CIS Microsoft Azure Foundations Benchmark', version: '2.0.0', url: 'https://www.cisecurity.org/benchmark/azure',
        controls_evaluated: 4, summary: { no_cumple: 2, riesgo_aceptado: 1, sin_evidencia: 1, cumple: 0 },
        controls: [
          { id: '3.7', title: "Ensure that 'Public access level' is disabled for storage accounts with blob containers", status: 'riesgo_aceptado', direct: true, active: 0, accepted: 1, evidence: [regla('storage.public-blob-access', 'Cuenta de almacenamiento con blobs públicos', 0, 1)] },
          { id: '6.2', title: 'Ensure that SSH access from the Internet is evaluated and restricted', status: 'no_cumple', direct: true, active: 1, accepted: 0, evidence: [regla('network.admin-port-open', 'Puerto de administración abierto a internet', 1)] },
          { id: '8.7', title: 'Ensure that Private Endpoints are Used for Azure Key Vault', status: 'no_cumple', direct: true, active: 1, accepted: 0, evidence: [regla('secrets.vault-public-network', 'Key Vault alcanzable desde red pública', 1)] },
          { id: '9.2', title: 'Ensure Web App Redirects All HTTP traffic to HTTPS in Azure App Service', status: 'sin_evidencia', direct: true, active: 0, accepted: 0, evidence: [{ ...regla('web.https-not-enforced', 'App Service sin HTTPS obligatorio', 0), status: 'sin_evidencia' }] },
        ],
      },
      {
        id: ISO, name: 'ISO/IEC 27001:2022 · Anexo A', version: '2022', url: 'https://www.iso.org/standard/27001',
        controls_evaluated: 3, summary: { no_cumple: 2, riesgo_aceptado: 0, sin_evidencia: 0, cumple: 1 },
        controls: [
          { id: 'A.5.9', title: 'Inventario de información y otros activos asociados', status: 'no_cumple', direct: false, active: 2, accepted: 0, evidence: [{ kind: 'classification', title: '3 de 5 activos inventariados con custodio', match: 'parcial', status: 'no_cumple', active: 2, accepted: 0 }] },
          { id: 'A.5.12', title: 'Clasificación de la información', status: 'cumple', direct: true, active: 0, accepted: 0, evidence: [{ kind: 'classification', title: '5 de 5 activos clasificados', match: 'directa', status: 'cumple', active: 0, accepted: 0 }] },
          { id: 'A.8.20', title: 'Seguridad de las redes', status: 'no_cumple', direct: true, active: 2, accepted: 0, evidence: [regla('network.admin-port-open', 'Puerto de administración abierto a internet', 1), regla('secrets.vault-public-network', 'Key Vault alcanzable desde red pública', 1)] },
        ],
      },
    ],
    rules: [
      { id: 'network.admin-port-open', title: 'Puerto de administración abierto a internet', severity_default: 'alta', description: 'Una regla de entrada permite RDP o SSH desde cualquier origen.', detection: 'Reglas Allow con origen * hacia 22 o 3389.', remediation: 'Restringir el origen o usar Azure Bastion.', references: ['https://learn.microsoft.com/azure/bastion/bastion-overview'], frameworks: { [CIS]: [{ control: '6.1', match: 'directa' }, { control: '6.2', match: 'directa' }], [ISO]: [{ control: 'A.8.20', match: 'directa' }, { control: 'A.8.22', match: 'parcial' }] }, status: 'no_cumple', evaluated: true, active: 1, accepted: 0, resolved: 0, by_severity: { critica: 1 } },
      { id: 'secrets.vault-public-network', title: 'Key Vault alcanzable desde red pública', severity_default: 'alta', description: 'El almacén de secretos acepta conexiones desde internet.', detection: 'publicNetworkAccess = Enabled y sin private endpoint.', remediation: 'Añadir private endpoint.', references: [], frameworks: { [CIS]: [{ control: '8.7', match: 'directa' }], [ISO]: [{ control: 'A.8.20', match: 'directa' }] }, status: 'no_cumple', evaluated: true, active: 1, accepted: 0, resolved: 0, by_severity: { alta: 1 } },
      { id: 'storage.public-blob-access', title: 'Cuenta de almacenamiento con blobs públicos', severity_default: 'alta', description: 'La cuenta permite contenedores con lectura anónima.', detection: 'allowBlobPublicAccess = true.', remediation: 'Deshabilitar allowBlobPublicAccess.', references: [], frameworks: { [CIS]: [{ control: '3.7', match: 'directa' }] }, status: 'riesgo_aceptado', evaluated: true, active: 0, accepted: 1, resolved: 0, by_severity: {} },
      { id: 'web.https-not-enforced', title: 'App Service sin HTTPS obligatorio', severity_default: 'alta', description: 'La aplicación responde por HTTP sin redirigir.', detection: 'httpsOnly = false.', remediation: 'Activar httpsOnly.', references: [], frameworks: { [CIS]: [{ control: '9.2', match: 'directa' }] }, status: 'sin_evidencia', evaluated: false, active: 0, accepted: 0, resolved: 1, by_severity: {} },
    ],
  };
}

function activo(nombre: string, tipo: string, clase: ClassifiedAsset['classification'], cid: [number, number, number], extra: Partial<ClassifiedAsset> = {}): ClassifiedAsset {
  return {
    uid: `azure:/subscriptions/${SUB_PROD}/resourcegroups/rg/providers/${tipo}/${nombre}`, name: nombre, type: tipo,
    group: 'rg-pagos-prod', account: 'Producción (demo)', environment: 'prod', classification: clase,
    confidentiality: cid[0], integrity: cid[1], availability: cid[2], score: cid[0] + cid[1] + cid[2],
    risk_required: cid[0] + cid[1] + cid[2] >= 6, custodian: 'equipo-pagos', method: 'automatica',
    reason: 'Producción · guarda datos o llaves', updated_by: 'recolector', updated_at: '2026-10-10T06:02:00Z',
    open_findings: 0, ...extra,
  };
}

export function classifiedAssets(extra: ClassifiedAsset[] = []): ClassifiedAssets {
  const items = [
    activo('kv-pagos-prod', 'microsoft.keyvault/vaults', 'Confidencial', [3, 3, 3], { open_findings: 1 }),
    activo('sql-pagos-prod', 'microsoft.sql/servers', 'Confidencial', [3, 3, 3]),
    activo('nsg-pagos-prod', 'microsoft.network/networksecuritygroups', 'Restringido', [2, 3, 3], { custodian: null, open_findings: 1, reason: 'Producción · cómputo o red expuesta' }),
    activo('app-web-dev', 'microsoft.web/sites', 'Uso interno', [1, 1, 1], { group: 'rg-web-dev', account: 'Laboratorio (demo)', environment: 'dev', custodian: null, risk_required: false, reason: 'Ambiente dev' }),
    activo('stwebdev01', 'microsoft.storage/storageaccounts', 'Restringido', [2, 2, 2], { group: 'rg-web-dev', account: 'Laboratorio (demo)', environment: 'dev', custodian: 'equipo-web', risk_required: false, method: 'manual', reason: 'Sitio estático con datos de prueba', updated_by: 'ana@contoso.example' }),
    ...extra,
  ];
  const clasificados = items.filter((a) => a.classification);
  const por = (c: string) => clasificados.filter((a) => a.classification === c).length;
  return {
    available: true,
    items,
    stats: {
      total: items.length, classified: clasificados.length,
      by_class: { Confidencial: por('Confidencial'), Restringido: por('Restringido'), 'Uso interno': por('Uso interno') },
      risk_required: items.filter((a) => a.risk_required).length, manual: items.filter((a) => a.method === 'manual').length,
      without_custodian: items.filter((a) => !a.custodian).length,
      average_score: Math.round((clasificados.reduce((n, a) => n + (a.score ?? 0), 0) / clasificados.length) * 100) / 100,
    },
    collected_at: '2026-10-10T06:02:00Z',
  };
}

/** Muchos activos sin hallazgos, para probar paginación y búsqueda. */
export function manyAssets(n: number): ClassifiedAsset[] {
  return Array.from({ length: n }, (_, i) => activo(`app-lote-${String(i + 1).padStart(3, '0')}`, 'microsoft.web/sites', 'Uso interno', [1, 1, 1], {
    environment: 'dev', risk_required: false, custodian: `equipo-${i % 3}`,
  }));
}

// ---------------------------------------------------------------- administración

export const adminDatabase = {
  configured: true,
  dialect: 'mssql',
  revision: '0003',
  rows: { accounts: 2, resources: 48, cost_daily: 1460, rules: 7, findings: 4, finding_events: 7, kpi_daily: 520, collector_runs: 84, audit_log: 3, asset_classifications: 48 },
  recent_runs: [
    { collector: 'readmodel', status: 'ok', started_at: '2026-10-10T06:04:10Z', finished_at: '2026-10-10T06:04:13Z', items: 7, error: null, detail: { seconds: 2.7 } },
    { collector: 'classification', status: 'ok', started_at: '2026-10-10T06:01:12Z', finished_at: '2026-10-10T06:01:13Z', items: 48, error: null, detail: { seconds: 0.6, nuevas: 0, cambiadas: 1, manuales: 1 } },
    { collector: 'costs', status: 'ok', started_at: '2026-10-10T06:01:14Z', finished_at: '2026-10-10T06:01:48Z', items: 98, error: null, detail: { seconds: 34, recovered_on_retry: 1 } },
    { collector: 'inventory', status: 'ok', started_at: '2026-10-10T06:01:10Z', finished_at: '2026-10-10T06:01:11Z', items: 48, error: null, detail: { seconds: 1.1 } },
  ],
};

/** Fila de /api/admin/audit (el panel la tipa dentro de AdminPage). */
export interface AuditRow {
  at: string;
  actor: string;
  role: Role;
  action: string;
  target: string | null;
  outcome: 'ok' | 'error';
  detail: Record<string, unknown>;
}

export const adminAudit: { configured: boolean; items: AuditRow[] } = {
  configured: true,
  items: [
    { at: '2026-10-10T14:20:00Z', actor: 'ana@contoso.example', role: 'operador', action: 'activo.clasificacion', target: 'azure:/x/stwebdev01', outcome: 'ok', detail: { classification: 'Restringido', reason: 'Sitio estático con datos de prueba' } },
    { at: '2026-10-09T16:05:00Z', actor: 'ana@contoso.example', role: 'operador', action: 'hallazgo.estado', target: 'azure:/x/stwebdev01', outcome: 'ok', detail: { status: 'aceptado', accepted_until: '2026-12-31' } },
    { at: '2026-10-08T10:41:00Z', actor: 'luis@contoso.example', role: 'administrador', action: 'k8s.reiniciar_cliente', target: null, outcome: 'ok', detail: {} },
  ],
};

export function connectedAccounts(): ConnectedAccounts {
  return {
    configured: true,
    inventory_at: '2026-10-10T06:01:11Z',
    costs_at: '2026-10-10T06:01:48Z',
    cost_days: 30,
    providers: [{
      name: 'azure', label: 'Microsoft Azure',
      capabilities: { inventario: true, costos: true, seguridad: true, iac: false, actividad: true },
      unavailable: { iac: 'No hay cuentas de estado de Terraform configuradas (TFSTATE_ACCOUNT).' },
      identity: { kind: 'identidad_administrada', client_id: '00000000-0000-4000-8000-0000000000c1' },
      cost_role: 'Cost Management Reader', accounts: 3, visible: 2, cost_denied: 1,
    }],
    accounts: [
      { uid: `azure:sub/${SUB_PROD}`, provider: 'azure', native_id: SUB_PROD, name: 'Producción (demo)', parent: null, first_seen: '2026-08-01T06:00:00Z', last_seen: '2026-10-10T06:00:00Z', visible: true, resources: 21, open_findings: 2, cost_30d: 71.4, currency: 'USD', cost_status: 'con_permiso' },
      { uid: `azure:sub/${SUB_LAB}`, provider: 'azure', native_id: SUB_LAB, name: 'Laboratorio (demo)', parent: null, first_seen: '2026-08-01T06:00:00Z', last_seen: '2026-10-10T06:00:00Z', visible: true, resources: 27, open_findings: 0, cost_30d: null, currency: null, cost_status: 'sin_permiso' },
      { uid: 'azure:sub/00000000-0000-4000-8000-000000000003', provider: 'azure', native_id: '00000000-0000-4000-8000-000000000003', name: 'Retirada (demo)', parent: null, first_seen: '2026-08-01T06:00:00Z', last_seen: '2026-09-15T06:00:00Z', visible: false, resources: 0, open_findings: 0, cost_30d: 0.4, currency: 'USD', cost_status: 'con_permiso' },
    ],
  };
}

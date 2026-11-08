/**
 * API simulado para las pruebas E2E.
 *
 * Responde con los datos ficticios de src/test/fixtures.ts (tipados contra el
 * contrato del API) y guarda estado para los flujos que escriben: clasificar un
 * activo o aceptar un riesgo cambian lo que devuelven las lecturas siguientes,
 * como en el backend real.
 *
 * Cada prueba falla si el panel pide un endpoint que no está simulado o si
 * aparece un error en la consola: así una ruta nueva sin datos de prueba o un
 * fallo de render no pasan desapercibidos.
 */
import { test as base, expect, type Page, type Request } from '@playwright/test';
import * as fx from '../src/test/fixtures';
import type { ClassifiedAsset, ManagedFinding, Role } from '../src/lib/types';

export const API_URL = 'http://api.cloudops.test';
/** Fecha fija de todas las pruebas: viernes 10 de octubre de 2026, 10:00 en Bogotá. */
export const AHORA = new Date('2026-10-10T10:00:00-05:00');

type Json = unknown;
type Handler = (req: Request, body: Record<string, unknown>) => Json | { status: number; body: Json } | Promise<Json>;

export interface ApiOptions {
  role: Role;
  /** Respuestas sustitutas por "MÉTODO /ruta" (sin query). */
  overrides: Record<string, Handler>;
  /** Mensajes de consola esperados (por ejemplo, el 503 de una prueba de error). */
  allowedConsoleErrors: RegExp[];
}

export interface ApiMock {
  calls: { method: string; path: string; body: Record<string, unknown> }[];
  /** Último cuerpo enviado a una ruta. */
  lastBody: (key: string) => Record<string, unknown> | undefined;
}

export class Respuesta {
  constructor(readonly status: number, readonly body: Json) {}
}

function rutas(role: Role): Record<string, Handler> {
  let activos = fx.classifiedAssets();
  let hallazgos = fx.managedFindings();
  const auditoria = structuredClone(fx.adminAudit);
  const auditar = (action: string, target: string, detail: Record<string, unknown>) =>
    auditoria.items.unshift({ at: AHORA.toISOString(), actor: fx.me(role).upn, role, action, target, outcome: 'ok', detail });

  const operador = () => fx.me(role).permissions.operador;
  const prohibido = new Respuesta(403, { detail: 'Esta acción requiere el rol operador.' });

  return {
    'GET /api/me': () => fx.me(role),
    'GET /api/inventory/health': () => ({ azureConnected: true }),
    'GET /api/inventory/subscriptions': () => fx.subscriptions,
    'GET /api/accounts': () => fx.cloudAccounts,
    'POST /api/inventory/summary': () => fx.inventorySummary,
    'POST /api/inventory/tag-compliance': () => fx.tagCompliance,
    'POST /api/inventory/history': () => fx.inventoryHistory,
    'POST /api/inventory/resources': () => fx.inventoryPage,
    'POST /api/inventory/manual-creations': () => fx.manualCreations,
    'GET /api/inventory/snapshots': () => fx.snapshots,
    'GET /api/inventory/report': () => fx.inventoryReport(),
    'GET /api/inventory/report/export': () => new Respuesta(200, 'Nube,Cuenta,Recurso\naws,AWS laboratorio (demo),lab-datos\n'),
    'GET /api/sync/status': () => fx.syncStatus,
    'GET /api/finops/costs': () => fx.costOverview,
    'GET /api/finops/report': () => fx.finopsReport,
    'GET /api/history/costs': (req) => fx.costHistory((new URL(req.url()).searchParams.get('period') ?? '30d') as '30d'),
    'GET /api/secops/report': () => fx.secopsReport,
    'GET /api/k8s/clusters': () => fx.k8sClusters,
    'GET /api/incidents': () => fx.incidents,
    'GET /api/incidents/stats': () => fx.incidentStats,
    'GET /api/silences': () => ({ items: [] }),
    'GET /api/settings': () => ({ sections: {
      gobierno: { values: { tags_obligatorias: ['Environment', 'Project', 'ManagedBy'], tags_showback: ['Project', 'Environment'] }, defaults: {}, origin: 'variable',
        schema: { tags_obligatorias: ['nombres', 20, false], tags_showback: ['nombres', 10, false] } },
      costos: { values: { presupuesto_azure_usd: 5, presupuesto_aws_usd: 5 }, defaults: {}, origin: 'variable',
        schema: { presupuesto_azure_usd: ['float', 0, 1000000], presupuesto_aws_usd: ['float', 0, 1000000] } },
      ia: { values: { max_consultas_hora: 30, max_consultas_dia: 150 }, defaults: {}, origin: 'variable',
        schema: { max_consultas_hora: ['int', 0, 10000], max_consultas_dia: ['int', 0, 100000] } },
    } }),
    'GET /api/settings-history': () => ({ items: [] }),
    'GET /api/checks': () => ({ items: [] }),
    'GET /api/ia/resumen': () => ({ days: 7, priced: true, median_ms: 2100,
      total: { calls: 12, errors: 1, input_tokens: 48000, output_tokens: 3200, cost_usd: 0.0304, p50_ms: 2100, p95_ms: 9800 },
      by_domain: { operacion: { calls: 4, errors: 0, input_tokens: 32000, output_tokens: 1800, cost_usd: 0.0196, p50_ms: 8200, p95_ms: 9800 },
        inicio: { calls: 8, errors: 1, input_tokens: 16000, output_tokens: 1400, cost_usd: 0.0108, p50_ms: 1900, p95_ms: 3100 } },
      by_use: { 'incidente.diagnostico': { calls: 4, errors: 0, input_tokens: 32000, output_tokens: 1800, cost_usd: 0.0196, p50_ms: 8200, p95_ms: 9800 },
        'asistente.chat': { calls: 8, errors: 1, input_tokens: 16000, output_tokens: 1400, cost_usd: 0.0108, p50_ms: 1900, p95_ms: 3100 } },
      tools: [{ name: 'estado_cluster', calls: 6, errors: 0 }, { name: 'cambios_recientes', calls: 4, errors: 0 }] }),
    'GET /api/ia/trazas': () => ({ total: 1, items: [{ trace_id: 'a1b2', name: 'invoke_agent incidente.diagnostico', start: '2026-10-10T06:10:00Z',
      duration_ms: 8200, spans: 5, attributes: { 'cloudops.use': 'incidente.diagnostico', 'gen_ai.usage.input_tokens': 8000, 'gen_ai.usage.output_tokens': 450 } }] }),
    'GET /api/activos/ficha': () => ({
      uid: 'azure:/subscriptions/1/x/stdatos', name: 'stdatos', provider: 'azure', type: 'storage.account',
      native_type: 'microsoft.storage/storageaccounts', region: 'eastus2', group: 'rg-datos', account: { uid: 'azure:sub/1', name: 'sub-lab' },
      tags: { Environment: 'dev', Project: 'datos' }, missing_tags: ['ManagedBy'], in_iac: false, created_by: 'ana@contoso.example',
      first_seen: '2026-09-02T10:00:00Z', last_seen: '2026-10-10T06:00:00Z', deleted_at: null,
      cost: { total_30d: 4.5, currency: 'USD', by_service: [{ service: 'Storage', cost: 4.1 }, { service: 'Bandwidth', cost: 0.4 }],
        daily: Array.from({ length: 30 }, (_, i) => ({ date: `2026-09-${String(i + 1).padStart(2, '0')}`, cost: 0.1 + (i % 5) * 0.03 })) },
      findings: [{ id: 2, title: 'Acceso público a blobs habilitado', severity: 'alta', status: 'abierto', owner: null, accepted_until: null,
        remediation: 'Desactivar allowBlobPublicAccess en la cuenta.' }],
      open_findings: 1, classification: { classification: 'Confidencial', confidentiality: 3, integrity: 2, availability: 2, custodian: 'ana@contoso.example' },
      cluster: null, incidents: [],
      timeline: [{ at: '2026-10-08T06:00:00Z', kind: 'hallazgo.detectado', actor: 'recolector', text: 'Acceso público a blobs habilitado: detectado' },
        { at: '2026-09-02T10:00:00Z', kind: 'recurso.visto', actor: 'ana@contoso.example', text: 'Apareció en el inventario, creado por ana@contoso.example' }],
    }),
    'GET /api/costos/ahorro/realizado': () => ({ days: 90, removed: [],
      applied: [{ id: 1, name: 'disk-old', category: 'Disco sin VM', expected_monthly: 3.5, applied_by: 'ana@contoso.example',
        applied_at: '2026-10-01T10:00:00Z', status: 'verificado', removed_at: '2026-10-05T06:00:00Z', realized_monthly: 3.8 }],
      totals: { applied_pending: 0, expected_monthly: 3.5, realized_monthly: 3.8, removed_monthly: 3.8 } }),
    'GET /api/costos/alertas': () => ({ open: 1, items: [{ id: 4, kind: 'anomalia', provider: 'azure', account: 'sub-lab', day: '2026-10-09',
      amount: 3.2, reference: 0.4, title: 'Gasto anómalo en sub-lab el 09-10', status: 'abierto', assignee: null, note: null,
      explanation: null, opened_at: '2026-10-10T06:04:00Z', updated_by: null }] }),
    'GET /api/activos/drift': () => ({ available: true, generated_at: '2026-10-10T06:03:00Z', states_read: 3, totals: { deleted: 1, tags: 1 },
      deleted: [{ id: '/subscriptions/1/resourcegroups/rg-datos/providers/microsoft.keyvault/vaults/kv-viejo', name: 'kv-viejo', terraform_type: 'azurerm_key_vault' }],
      tags: [{ uid: 'azure:/subscriptions/1/x/stdatos', name: 'stdatos', type: 'storage.account',
        changes: [{ tag: 'Environment', terraform: 'prod', real: 'dev' }, { tag: 'Owner', terraform: 'plataforma', real: null }] }] }),
    'GET /api/activos/recursos': () => ({ total: 1, providers: ['azure'], items: [{ uid: 'azure:/subscriptions/1/x/stdatos', provider: 'azure',
      account_uid: 'azure:sub/1', account: 'sub-lab', name: 'stdatos', type: 'storage.account', region: 'eastus2', cost_30d: 4.5,
      currency: 'USD', in_iac: false, classification: 'Confidencial' }] }),
    'GET /api/notifications': () => ({ mode: 'registro', stats: { total: 1, enviados: 1, silenciados: 0, duplicados: 0, fallidos: 0 },
      items: [{ at: '2026-10-10T06:05:00Z', dominio: 'riesgo', tipo: 'atencion_diaria', severidad: 'alta', clave: 'diario:1',
        titulo: 'CloudOps Copilot: requiere atención', enlace: 'https://panel.example/#/riesgo/hallazgos', canal: 'discord.com',
        modo: 'registro', decision: 'enviado', silencio: null, enviado: true, error: null }] }),
    'GET /api/settings/incidents': () => ({ values: { ventana_tormenta_seg: 120, umbral_tormenta: 3, foto_vieja_min: 15,
      diagnosticar: ['critica', 'alta', 'media'], avisar: ['critica', 'alta', 'media'], postmortem: true, max_diagnosticos_hora: 0 }, limits: {} }),
    'GET /api/incidents/2': () => fx.incidentDetail,
    'POST /api/incidents/2/feedback': () => ({ id: 2, feedback: 'correcto' }),
    'GET /api/k8s/clusters/homelab': () => fx.k8sHomelab,
    'GET /api/activos/kubernetes/homelab/historial': () => ({ cluster: 'homelab', days: 30, median_minutes: 18,
      open: [{ title: 'CrashLoopBackOff: grafana-7d9c6b5f4-x2kqp', severity: 'critica', category: 'pod', namespace: 'monitoring',
        resource: 'pod/grafana-7d9c6b5f4-x2kqp', desde: '2026-10-10T08:40:00Z', hasta: null, minutes: 80 }],
      closed: [{ title: 'Deployment degradado: prometheus', severity: 'alta', category: 'carga', namespace: 'monitoring',
        resource: 'deployment/prometheus', desde: '2026-10-09T14:00:00Z', hasta: '2026-10-09T14:18:00Z', minutes: 18 }] }),
    'GET /api/settings/k8s/homelab': () => ({ values: { namespaces_ignorados: [], reinicios: 5, gracia_min: 10, avisar: true, avisar_severidades: ['critica', 'alta'] } }),
    'PUT /api/settings/k8s/homelab': (req) => ({ values: req.postDataJSON() }),
    'POST /api/k8s/clusters/homelab/incidents': () => ({ incident: 3, action: 'nuevo' }),
    'GET /api/incidents/3': () => ({ ...fx.incidentDetail, id: 3 }),
    'GET /api/secops/exposure': () => fx.riskExposure,
    'POST /api/iac/terraform-coverage': () => fx.terraformCoverage,
    'GET /api/findings': () => hallazgos,
    'GET /api/compliance': () => fx.complianceStatus(),
    'GET /api/compliance/assets': () => activos,
    'GET /api/compliance/assets/export': () => new Respuesta(200, 'Activo,Clasificación\nkv-pagos-prod,Confidencial\n'),
    'GET /api/admin/database': () => (role === 'administrador' ? fx.adminDatabase : new Respuesta(403, { detail: 'Requiere administrador.' })),
    'GET /api/admin/audit': () => (role === 'administrador' ? auditoria : new Respuesta(403, { detail: 'Requiere administrador.' })),
    'GET /api/admin/accounts': () => (role === 'administrador' ? fx.connectedAccounts() : new Respuesta(403, { detail: 'Requiere administrador.' })),

    'POST /api/compliance/assets/classification': (_req, b) => {
      if (!operador()) return prohibido;
      if (!String(b.reason ?? '').trim()) return new Respuesta(400, { detail: 'Cambiar la clasificación exige un motivo.' });
      const previo = activos.items.find((a) => a.uid === b.resource_uid);
      if (!previo) return new Respuesta(404, { detail: 'El recurso no existe en el inventario.' });
      const c = [b.confidentiality, b.integrity, b.availability].map(Number);
      const nuevo: ClassifiedAsset = {
        ...previo, classification: b.classification as ClassifiedAsset['classification'], confidentiality: c[0], integrity: c[1],
        availability: c[2], score: c[0] + c[1] + c[2], risk_required: Boolean(b.risk_required), method: 'manual',
        reason: String(b.reason), custodian: (b.custodian as string | null) || previo.custodian, updated_by: fx.me(role).upn,
        updated_at: AHORA.toISOString(),
      };
      const items = activos.items.map((a) => (a.uid === nuevo.uid ? nuevo : a));
      activos = { ...activos, items, stats: { ...activos.stats, manual: items.filter((a) => a.method === 'manual').length } };
      auditar('activo.clasificacion', nuevo.uid, { classification: nuevo.classification, reason: nuevo.reason });
      return nuevo;
    },
    'POST /api/compliance/assets/classification/restore': (_req, b) => {
      if (!operador()) return prohibido;
      const original = fx.classifiedAssets().items.find((a) => a.uid === b.resource_uid)!;
      const restaurado: ClassifiedAsset = { ...original, method: 'automatica', reason: 'Ambiente dev' };
      activos = { ...activos, items: activos.items.map((a) => (a.uid === restaurado.uid ? restaurado : a)) };
      auditar('activo.clasificacion_automatica', restaurado.uid, { classification: restaurado.classification });
      return restaurado;
    },
    'POST /api/findings/{id}/status': (req, b) => {
      if (!operador()) return prohibido;
      const id = Number(new URL(req.url()).pathname.split('/')[3]);
      const f = hallazgos.items.find((h) => h.id === id);
      if (!f) return new Respuesta(404, { detail: 'No existe.' });
      const nuevo: ManagedFinding = {
        ...f, status: b.status as ManagedFinding['status'], accepted_until: (b.accepted_until as string | null) ?? null,
        owner: b.status === 'asumido' ? ((b.owner as string) || fx.me(role).upn) : f.owner,
      };
      const items = hallazgos.items.map((h) => (h.id === id ? nuevo : h));
      const porEstado: ManagedFinding['status'][] = ['abierto', 'asumido', 'aceptado', 'resuelto'];
      hallazgos = { ...hallazgos, items, by_status: Object.fromEntries(porEstado.map((s) => [s, items.filter((h) => h.status === s).length])) };
      auditar('hallazgo.estado', f.resource_uid, { status: b.status, accepted_until: b.accepted_until, note: b.note });
      return nuevo;
    },
    'GET /api/findings/{id}/events': () => fx.findingEvents,
  };
}

function clave(method: string, pathname: string): string[] {
  // "POST /api/findings/2/status" también responde a "POST /api/findings/{id}/status".
  return [`${method} ${pathname}`, `${method} ${pathname.replace(/\/\d+(?=\/|$)/g, '/{id}')}`];
}

export async function mockApi(page: Page, opts: ApiOptions): Promise<ApiMock & { unhandled: string[] }> {
  const tabla = { ...rutas(opts.role), ...opts.overrides };
  const calls: ApiMock['calls'] = [];
  const unhandled: string[] = [];

  await page.route(`${API_URL}/**`, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const body = (req.postDataJSON() as Record<string, unknown> | null) ?? {};
    calls.push({ method: req.method(), path: url.pathname, body });
    const handler = clave(req.method(), url.pathname).map((k) => tabla[k]).find(Boolean);
    if (!handler) {
      unhandled.push(`${req.method()} ${url.pathname}`);
      return route.fulfill({ status: 404, json: { detail: 'Sin simular en e2e/mock-api.ts' } });
    }
    const r = await handler(req, body);
    const { status, body: cuerpo } = r instanceof Respuesta ? r : { status: 200, body: r };
    if (typeof cuerpo === 'string') return route.fulfill({ status, body: cuerpo, contentType: 'text/csv; charset=utf-8' });
    return route.fulfill({ status, json: cuerpo });
  });

  return {
    calls,
    unhandled,
    lastBody: (key) => [...calls].reverse().find((c) => `${c.method} ${c.path}` === key)?.body,
  };
}

/**
 * `test` con el API simulado y el reloj fijo. Opciones por archivo o por
 * prueba: `test.use({ role: 'lector' })`.
 */
export const test = base.extend<ApiOptions & { api: ApiMock }>({
  role: ['administrador', { option: true }],
  overrides: [{}, { option: true }],
  allowedConsoleErrors: [[], { option: true }],
  // Automático: toda prueba corre con el API simulado aunque no lo pida.
  api: [async ({ page, role, overrides, allowedConsoleErrors }, use) => {
    const errores: string[] = [];
    page.on('pageerror', (e) => errores.push(e.message));
    page.on('console', (m) => {
      if (m.type() === 'error' && !allowedConsoleErrors.some((r) => r.test(m.text()))) errores.push(m.text());
    });
    await page.clock.setFixedTime(AHORA);
    const api = await mockApi(page, { role, overrides, allowedConsoleErrors });
    await use(api);
    expect(api.unhandled, 'endpoints sin simular').toEqual([]);
    expect(errores, 'errores en la consola del navegador').toEqual([]);
  }, { auto: true }],
});

export { expect };

/** Abre una ruta del panel y espera a que su encabezado esté visible. */
export async function abrir(page: Page, ruta: string, titulo: string | RegExp) {
  await page.goto(`/#/${ruta}`);
  await expect(page.getByRole('heading', { level: 1, name: titulo })).toBeVisible();
}

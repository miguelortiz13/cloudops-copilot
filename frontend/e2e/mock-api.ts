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
    'POST /api/inventory/summary': () => fx.inventorySummary,
    'POST /api/inventory/tag-compliance': () => fx.tagCompliance,
    'POST /api/inventory/history': () => fx.inventoryHistory,
    'POST /api/inventory/resources': () => fx.inventoryPage,
    'POST /api/inventory/manual-creations': () => fx.manualCreations,
    'GET /api/inventory/snapshots': () => fx.snapshots,
    'GET /api/sync/status': () => fx.syncStatus,
    'GET /api/finops/costs': () => fx.costOverview,
    'GET /api/finops/report': () => fx.finopsReport,
    'GET /api/history/costs': (req) => fx.costHistory((new URL(req.url()).searchParams.get('period') ?? '30d') as '30d'),
    'GET /api/secops/report': () => fx.secopsReport,
    'GET /api/secops/exposure': () => fx.riskExposure,
    'POST /api/iac/terraform-coverage': () => fx.terraformCoverage,
    'GET /api/findings': () => hallazgos,
    'GET /api/compliance': () => fx.complianceStatus(),
    'GET /api/compliance/assets': () => activos,
    'GET /api/compliance/assets/export': () => new Respuesta(200, 'Activo,Clasificación\nkv-pagos-prod,Confidencial\n'),
    'GET /api/admin/database': () => (role === 'administrador' ? fx.adminDatabase : new Respuesta(403, { detail: 'Requiere administrador.' })),
    'GET /api/admin/audit': () => (role === 'administrador' ? auditoria : new Respuesta(403, { detail: 'Requiere administrador.' })),

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

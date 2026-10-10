import { useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { get } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, number } from '../../lib/format';
import type { Role } from '../../lib/types';
import { useApp } from '../../state/hooks';
import {
  Card, Empty, ErrorState, Loading, Notice, PageHeader, Section, Segmented, StatTile, Tabs,
} from '../../components/ui';

type View = 'actividad' | 'plataforma';

interface AuditItem {
  at: string;
  actor: string;
  role: Role;
  action: string;
  target: string | null;
  outcome: 'ok' | 'error';
  detail: Record<string, unknown>;
}

interface Run {
  collector: string;
  status: 'ok' | 'parcial' | 'error' | 'en_curso';
  started_at: string;
  finished_at: string | null;
  items: number;
  error: string | null;
  detail: Record<string, unknown>;
}

interface DbStatus {
  configured: boolean;
  dialect?: string;
  revision?: string | null;
  rows?: Record<string, number | null>;
  recent_runs?: Run[];
  message?: string;
}

const ROLE_LABEL: Record<Role, string> = { lector: 'Lector', operador: 'Operador', administrador: 'Administrador' };
const ORIGEN: Record<string, string> = {
  grupo: 'por tu grupo de seguridad de Entra ID',
  app_role: 'por un app role asignado en Entra ID',
  por_defecto: 'por defecto (sin grupo ni app role)',
  sin_autenticacion: 'porque la autenticación está desactivada',
};

/** Acciones auditadas (app/core/audit.py) en lenguaje de persona. */
const ACCION: Record<string, string> = {
  'hallazgo.estado': 'Cambió el estado de un hallazgo',
  'inventario.sincronizar': 'Ejecutó la sincronización del inventario',
  'k8s.chat': 'Consultó al agente de Kubernetes',
  'k8s.incidencias': 'Pidió las incidencias de un clúster',
  'k8s.resumen': 'Pidió el resumen de un clúster',
  'k8s.logs': 'Leyó los logs de un pod',
  'k8s.reiniciar_cliente': 'Reinició el cliente de Kubernetes',
  'teams.alerta_prueba': 'Envió una alerta de prueba a Teams',
};

const FAMILIAS = [
  { id: 'todas', label: 'Todas' },
  { id: 'hallazgo', label: 'Hallazgos' },
  { id: 'k8s', label: 'Kubernetes' },
  { id: 'inventario', label: 'Sincronización' },
  { id: 'teams', label: 'Teams' },
] as const;

const RECOLECTOR: Record<string, string> = {
  inventory: 'Inventario', costs: 'Costos', findings: 'Hallazgos', kpis: 'KPIs',
  costcache: 'Caché de costos en vivo', readmodel: 'Vistas del panel',
};

function Outcome({ ok, label }: { ok: boolean; label?: string }) {
  return (
    <span className="badge">
      <span className={`dot ${ok ? 'dot-good' : 'dot-critical'}`} aria-hidden="true" />
      {label ?? (ok ? 'Correcto' : 'Error')}
    </span>
  );
}

/** Resumen legible del detalle de una acción. */
function resumen(a: AuditItem): string {
  const d = a.detail ?? {};
  const partes: string[] = [];
  if (d.status) partes.push(`→ ${String(d.status)}`);
  if (d.accepted_until) partes.push(`hasta ${String(d.accepted_until)}`);
  if (d.note) partes.push(`“${String(d.note)}”`);
  if (d.pregunta) partes.push(`“${String(d.pregunta)}”`);
  if (d.tipo) partes.push(`tipo ${String(d.tipo)}`);
  if (d.error) partes.push(String(d.error));
  return partes.join(' · ');
}

/**
 * Administración de la plataforma (solo administradores).
 *
 * Abrir esta sección consulta la base de datos directamente (no hay vista
 * precalculada): despierta Azure SQL si estaba pausada. Es una consulta
 * ocasional de una persona, dentro del presupuesto del cupo gratuito.
 */
export function AdminPage({ view, onView }: { view: string | undefined; onView: (v: View) => void }) {
  const { can, me } = useApp();
  const active: View = view === 'plataforma' ? 'plataforma' : 'actividad';

  if (me && !can('administrador')) {
    return (
      <>
        <PageHeader title="Administración" />
        <Empty title="Requiere el rol Administrador">Tu rol es {ROLE_LABEL[me.role]}. Pídele acceso a un administrador de la plataforma.</Empty>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Administración"
        description="Quién hizo qué en la plataforma, quién tiene acceso y cómo están la base de datos y los recolectores."
      />
      <Tabs<View>
        value={active}
        onChange={onView}
        tabs={[
          { id: 'actividad', label: 'Actividad de usuarios' },
          { id: 'plataforma', label: 'Base y recolectores' },
        ]}
      />
      {active === 'actividad' ? <Activity /> : <Platform />}
    </>
  );
}

function Activity() {
  const { me } = useApp();
  const { data, error, loading, refreshing, reload } = useApi<{ configured: boolean; items: AuditItem[] }>(
    'admin-audit', () => get('/api/admin/audit?limit=500'),
  );
  const [familia, setFamilia] = useState<(typeof FAMILIAS)[number]['id']>('todas');
  const [q, setQ] = useState('');

  const items = useMemo(() => (data?.items ?? []).filter((a) =>
    (familia === 'todas' || a.action.startsWith(`${familia}.`))
    && (!q || `${a.actor} ${a.target ?? ''} ${resumen(a)}`.toLowerCase().includes(q.toLowerCase()))), [data, familia, q]);

  const usuarios = new Set((data?.items ?? []).map((a) => a.actor)).size;
  const errores = (data?.items ?? []).filter((a) => a.outcome === 'error').length;

  return (
    <div className="stack" style={{ gap: 24 }}>
      {me && (
        <Card title="Tu acceso">
          <dl className="kv">
            <dt>Usuario</dt><dd>{me.name} {me.upn && <span className="muted">({me.upn})</span>}</dd>
            <dt>Rol</dt><dd><strong>{ROLE_LABEL[me.role]}</strong>, {ORIGEN[me.role_source ?? 'por_defecto']}</dd>
            {!me.auth_enabled && <><dt>Autenticación</dt><dd>Desactivada (desarrollo local): todos son administradores.</dd></>}
          </dl>
        </Card>
      )}

      {loading && <Loading label="Leyendo la auditoría…" />}
      {error && !data && <ErrorState error={error} onRetry={reload} />}
      {data && !data.configured && <Notice>Sin base de datos: la auditoría solo queda en el log del API.</Notice>}

      {data?.configured && (
        <>
          <div className="grid grid-4">
            <StatTile refreshing={refreshing} label="Acciones registradas" value={number(data.items.length)} meta="Las últimas 500" />
            <StatTile refreshing={refreshing} label="Usuarios" value={number(usuarios)} meta="Con al menos una acción" />
            <StatTile refreshing={refreshing} label="Con error" value={number(errores)} meta="La acción se intentó y falló" />
            <StatTile refreshing={refreshing} label="Última acción" value={data.items[0] ? dateTime(data.items[0].at) : '—'} />
          </div>

          <Section
            title="Actividad de usuarios"
            description="Cada acción que cambia algo o actúa sobre la nube. Los intentos sin permiso (403) quedan solo en el log del API."
            actions={
              <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                <div className="input-icon" style={{ width: 220 }}>
                  <Search size={14} />
                  <input className="input" placeholder="Usuario u objeto" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar" />
                </div>
                <Segmented label="Tipo" value={familia} onChange={setFamilia} options={FAMILIAS.map((f) => ({ id: f.id, label: f.label }))} />
              </div>
            }
          >
            <Card flush refreshing={refreshing}>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr><th>Fecha</th><th>Usuario</th><th>Acción</th><th>Resultado</th></tr>
                  </thead>
                  <tbody>
                    {items.map((a, i) => (
                      <tr key={`${a.at}-${i}`}>
                        <td className="secondary" style={{ whiteSpace: 'nowrap' }}>{dateTime(a.at)}</td>
                        <td>
                          <span className="primary-cell">{a.actor}</span>
                          <span className="sub">{ROLE_LABEL[a.role] ?? a.role}</span>
                        </td>
                        <td>
                          <span className="primary-cell">{ACCION[a.action] ?? a.action}</span>
                          {a.target && <span className="sub mono truncate" style={{ maxWidth: 520 }} title={a.target}>{a.target.replace(/^azure:/, '')}</span>}
                          {resumen(a) && <span className="sub">{resumen(a)}</span>}
                        </td>
                        <td><Outcome ok={a.outcome === 'ok'} /></td>
                      </tr>
                    ))}
                    {items.length === 0 && (
                      <tr><td colSpan={4} className="table-empty">{data.items.length ? 'Ninguna acción coincide con el filtro.' : 'Todavía no hay acciones registradas.'}</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </Card>
          </Section>
        </>
      )}
    </div>
  );
}

function Platform() {
  const { data, error, loading, refreshing, reload } = useApi<DbStatus>('admin-db', () => get('/api/admin/database'));

  if (loading) return <Loading label="Consultando la base (puede tardar un minuto si estaba pausada)…" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  if (!data.configured) return <Notice>{data.message ?? 'Sin base de datos configurada.'}</Notice>;

  const runs = data.recent_runs ?? [];
  const ultimas = Object.keys(RECOLECTOR).map((c) => runs.find((r) => r.collector === c)).filter(Boolean) as Run[];

  return (
    <div className="stack" style={{ gap: 24 }}>
      <div className="grid grid-4">
        <StatTile refreshing={refreshing} label="Esquema" value={data.revision ?? 'Sin migrar'} meta={data.dialect === 'mssql' ? 'Azure SQL' : data.dialect} />
        <StatTile refreshing={refreshing} label="Recursos" value={number(data.rows?.resources ?? 0)} meta={`${number(data.rows?.accounts ?? 0)} suscripciones`} />
        <StatTile refreshing={refreshing} label="Filas de costo" value={number(data.rows?.cost_daily ?? 0)} meta="Gasto diario por recurso y servicio" />
        <StatTile refreshing={refreshing} label="Hallazgos" value={number(data.rows?.findings ?? 0)} meta={`${number(data.rows?.finding_events ?? 0)} eventos de historial`} />
      </div>

      <div className="grid grid-main-side">
        <Section title="Ejecuciones de los recolectores" description="El job diario corre a las 06:00 UTC; cada recolector deja aquí su resultado.">
          <Card flush refreshing={refreshing}>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Recolector</th><th>Inicio</th><th className="num">Elementos</th><th className="num">Duración</th><th>Resultado</th></tr></thead>
                <tbody>
                  {runs.map((r, i) => (
                    <tr key={`${r.started_at}-${i}`}>
                      <td className="primary-cell">{RECOLECTOR[r.collector] ?? r.collector}</td>
                      <td className="secondary" style={{ whiteSpace: 'nowrap' }}>{dateTime(r.started_at)}</td>
                      <td className="num">{number(r.items)}</td>
                      <td className="num secondary">{typeof r.detail?.seconds === 'number' ? `${r.detail.seconds} s` : '—'}</td>
                      <td>
                        <Outcome ok={r.status === 'ok'} label={{ ok: 'Correcto', parcial: 'Parcial', error: 'Error', en_curso: 'En curso' }[r.status]} />
                        {r.error && <span className="sub" title={r.error}>{r.error.slice(0, 90)}</span>}
                      </td>
                    </tr>
                  ))}
                  {runs.length === 0 && <tr><td colSpan={5} className="table-empty">El recolector todavía no ha corrido.</td></tr>}
                </tbody>
              </table>
            </div>
          </Card>
        </Section>

        <Section title="Estado por recolector">
          <Card refreshing={refreshing}>
            <div className="stack" style={{ gap: 0 }}>
              {Object.entries(RECOLECTOR).map(([id, label], i) => {
                const r = ultimas.find((u) => u.collector === id);
                return (
                  <div key={id} className="spread" style={{ padding: '10px 0', borderTop: i ? '1px solid var(--border)' : 0, fontSize: 13 }}>
                    <span>{label}</span>
                    {r ? <Outcome ok={r.status === 'ok'} label={dateTime(r.finished_at ?? r.started_at)} /> : <span className="muted">Sin ejecuciones</span>}
                  </div>
                );
              })}
            </div>
          </Card>
          <Card title="Filas por tabla" refreshing={refreshing}>
            <div className="stack" style={{ gap: 0 }}>
              {Object.entries(data.rows ?? {}).map(([t, n], i) => (
                <div key={t} className="spread" style={{ padding: '8px 0', borderTop: i ? '1px solid var(--border)' : 0, fontSize: 13 }}>
                  <span className="mono">{t}</span>
                  <strong className="num">{n === null ? '—' : number(n)}</strong>
                </div>
              ))}
            </div>
          </Card>
        </Section>
      </div>
    </div>
  );
}

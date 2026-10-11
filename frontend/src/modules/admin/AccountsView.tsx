import { get } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, day, money, number } from '../../lib/format';
import type { Capability, ConnectedAccount, ConnectedAccounts, ConnectedProvider, CostAccess } from '../../lib/types';
import { Card, ErrorState, Loading, Notice, Section, StatTile } from '../../components/ui';

const CAPACIDAD: Record<Capability, string> = {
  inventario: 'Inventario',
  costos: 'Costos',
  seguridad: 'Seguridad',
  iac: 'Estados de Terraform',
  actividad: 'Historial de creaciones',
};

const COSTOS: Record<CostAccess, { label: string; dot?: string }> = {
  con_permiso: { label: 'Con permiso', dot: 'dot-good' },
  sin_permiso: { label: 'Sin permiso', dot: 'dot-critical' },
  fallo: { label: 'Falló la última vez', dot: 'dot-warning' },
  sin_dato: { label: 'Sin dato' },
};

function Estado({ label, dot }: { label: string; dot?: string }) {
  return (
    <span className="badge">
      <span className={`dot ${dot ?? ''}`} aria-hidden="true" style={dot ? undefined : { background: 'var(--border-strong)' }} />
      {label}
    </span>
  );
}

/**
 * Cuentas conectadas: qué ve la plataforma de cada nube y con qué permisos
 * efectivos, según lo que el recolector diario logró leer. No consulta la nube.
 */
export function AccountsView() {
  const { data, error, loading, refreshing, reload } = useApi<ConnectedAccounts>('admin-accounts', () => get('/api/admin/accounts'));

  if (loading) return <Loading label="Consultando la base (puede tardar un minuto si estaba pausada)…" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  if (!data.configured) return <Notice>Sin base de datos: las cuentas conectadas salen de lo que guarda el recolector diario.</Notice>;

  const cuentas = data.accounts;
  const visibles = cuentas.filter((c) => c.visible).length;
  const sinPermiso = cuentas.filter((c) => c.cost_status === 'sin_permiso');
  const perdidas = cuentas.filter((c) => !c.visible);

  return (
    <div className="stack" style={{ gap: 24 }}>
      <div className="grid grid-4">
        <StatTile refreshing={refreshing} label="Cuentas conectadas" value={number(cuentas.length)}
          meta={`${number(data.providers.length)} proveedor(es)`} />
        <StatTile refreshing={refreshing} icon={<span className={`dot ${visibles === cuentas.length ? 'dot-good' : 'dot-warning'}`} />}
          label="Visibles en el inventario" value={number(visibles)} unit={`de ${number(cuentas.length)}`}
          meta={data.inventory_at ? `Recolección del ${dateTime(data.inventory_at)}` : 'Sin recolección de inventario'} />
        <StatTile refreshing={refreshing} icon={sinPermiso.length ? <span className="dot dot-critical" /> : undefined}
          label="Sin permiso de costos" value={number(sinPermiso.length)}
          meta={sinPermiso.length ? 'Su gasto no se conoce: no es cero' : 'Todas entregan su gasto'} />
        <StatTile refreshing={refreshing} label="Recursos" value={number(cuentas.reduce((n, c) => n + c.resources, 0))}
          meta={`${number(cuentas.reduce((n, c) => n + c.open_findings, 0))} hallazgo(s) activos`} />
      </div>

      {perdidas.length > 0 && (
        <Notice tone="warning">
          {perdidas.length === 1 ? 'Una cuenta dejó' : `${perdidas.length} cuentas dejaron`} de aparecer en la última recolección:
          la identidad de la plataforma perdió el acceso o la cuenta se dio de baja. Sus datos anteriores se conservan.
        </Notice>
      )}

      {data.providers.map((p) => <ProviderCard key={p.name} provider={p} refreshing={refreshing} />)}

      <Section
        title="Cuentas"
        description={`Permisos efectivos según la última recolección. El gasto es de los últimos ${data.cost_days ?? 30} días con datos.`}
      >
        <Card flush refreshing={refreshing}>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Cuenta</th><th>Inventario</th><th>Costos</th><th className="num">Recursos</th><th className="num">Hallazgos</th><th className="num">Gasto</th><th>Vista por última vez</th></tr>
              </thead>
              <tbody>
                {cuentas.map((c) => <AccountRow key={c.uid} c={c} />)}
                {cuentas.length === 0 && <tr><td colSpan={7} className="table-empty">El recolector todavía no registró cuentas.</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>
      </Section>
    </div>
  );
}

function AccountRow({ c }: { c: ConnectedAccount }) {
  const costos = COSTOS[c.cost_status];
  return (
    <tr>
      <td>
        <span className="primary-cell">{c.name}</span>
        <span className="sub mono">{c.native_id}</span>
      </td>
      <td>{c.visible ? <Estado label="Visible" dot="dot-good" /> : <Estado label="No visible" dot="dot-warning" />}</td>
      <td><Estado {...costos} /></td>
      <td className="num">{number(c.resources)}</td>
      <td className="num">{c.open_findings ? number(c.open_findings) : <span className="muted">0</span>}</td>
      <td className="num">{c.cost_30d === null ? <span className="muted" title="Sin dato de costos para esta cuenta">—</span> : money(c.cost_30d, c.currency ?? 'USD')}</td>
      <td className="secondary" style={{ whiteSpace: 'nowrap' }}>
        {day(c.last_seen)}
        <span className="sub">desde el {day(c.first_seen)}</span>
      </td>
    </tr>
  );
}

function ProviderCard({ provider: p, refreshing }: { provider: ConnectedProvider; refreshing: boolean }) {
  const identidad = p.identity?.kind === 'identidad_administrada'
    ? <>Identidad administrada <span className="mono">{p.identity.client_id}</span></>
    : p.identity ? 'Credencial por defecto (sesión de desarrollo)' : null;
  return (
    <Section title={p.label} description={identidad ? <>Se conecta con: {identidad}. Solo lectura.</> : undefined}>
      <div className="grid grid-main-side">
        <Card title="Capacidades" subtitle="Lo que la plataforma puede mostrar de esta nube" refreshing={refreshing}>
          {p.capabilities ? (
            <div className="stack" style={{ gap: 0 }}>
              {(Object.keys(CAPACIDAD) as Capability[]).map((cap, i) => {
                const activa = p.capabilities![cap];
                const motivo = p.unavailable[cap];
                return (
                  <div key={cap} style={{ padding: '10px 0', borderTop: i ? '1px solid var(--border)' : 0, fontSize: 13 }}>
                    <div className="spread">
                      <span>{CAPACIDAD[cap]}</span>
                      {activa && !motivo ? <Estado label="Activa" dot="dot-good" />
                        : activa ? <Estado label="Sin datos" dot="dot-warning" /> : <Estado label="No configurada" />}
                    </div>
                    {motivo && <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{motivo}</div>}
                  </div>
                );
              })}
            </div>
          ) : (
            <span className="muted" style={{ fontSize: 13 }}>Se conocerán con la próxima recolección.</span>
          )}
        </Card>
        <Card title="Permisos" refreshing={refreshing}>
          <div className="stack" style={{ gap: 8, fontSize: 13 }}>
            <span>{number(p.visible)} de {number(p.accounts)} cuenta(s) visibles.</span>
            {p.cost_denied > 0 && p.cost_role ? (
              <Notice tone="warning">
                {p.cost_denied === 1 ? 'Una cuenta no entrega' : `${p.cost_denied} cuentas no entregan`} su gasto: falta el rol <strong>{p.cost_role}</strong> para
                la identidad de la plataforma en esa cuenta.
              </Notice>
            ) : (
              <span className="muted">Todas las cuentas visibles entregan su gasto.</span>
            )}
          </div>
        </Card>
      </div>
    </Section>
  );
}

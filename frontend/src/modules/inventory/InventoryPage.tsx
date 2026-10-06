import { Fragment, useEffect, useState } from 'react';
import { Copy, Download, Eye, MessageSquare, Search, X } from 'lucide-react';
import { download, post } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, number, percent, shortType } from '../../lib/format';
import type { Distribution, HistorySeries, InventoryPage as Page, InventoryResource, InventorySummary, TagCompliance } from '../../lib/types';
import { useApp } from '../../state/hooks';
import { Sparkline } from '../../components/charts';
import {
  Badge, Card, Delta, Drawer, ErrorState, Loading, Meter, Notice, PageHeader, Pagination, Section,
  Segmented, StatTile, StatusBadge, type Polarity,
} from '../../components/ui';

const PAGE_SIZE = 25;

function complianceTone(pct: number): 'good' | 'warning' | 'critical' {
  return pct >= 90 ? 'good' : pct >= 60 ? 'warning' : 'critical';
}

function DistributionList({ items }: { items: Distribution[] }) {
  return (
    <div className="barlist">
      {items.slice(0, 8).map((d) => (
        <div key={d.key} className="barlist-row">
          <span className="barlist-label truncate">{d.key || '—'}</span>
          <span className="barlist-track">
            <span className="barlist-bar" style={{ width: `${Math.max(d.percentage, 1)}%` }} />
          </span>
          <span className="barlist-value">{number(d.count)}<small>{percent(d.percentage)}</small></span>
        </div>
      ))}
      {!items.length && <div className="empty">Sin datos</div>}
    </div>
  );
}

const TRENDS: { field: keyof HistorySeries['points'][number]; label: string; polarity: Polarity; suffix?: string }[] = [
  { field: 'tagCompliancePercentage', label: 'Cumplimiento de tags', polarity: 'up-good', suffix: ' %' },
  { field: 'nonCompliantResources', label: 'Recursos no conformes', polarity: 'up-bad' },
  { field: 'shadowItCandidates', label: 'Candidatos a Shadow IT', polarity: 'up-bad' },
  { field: 'totalResources', label: 'Recursos totales', polarity: 'neutral' },
];

function TrendRow({ history }: { history: HistorySeries | null }) {
  if (!history) return null;
  if (!history.available || history.points.length < 2) {
    return (
      <Notice>
        La evolución histórica se acumula un punto por día desde la primera consulta. Aún no hay dos días para comparar.
      </Notice>
    );
  }
  return (
    <div className="grid grid-4">
      {TRENDS.map((m) => {
        const values = history.points.map((p) => Number(p[m.field] ?? 0));
        const last = values[values.length - 1];
        return (
          <div key={m.field} className="card stat">
            <div className="stat-label">{m.label}</div>
            <div className="spread">
              <div className="stat-value" style={{ fontSize: 22 }}>{number(last, m.suffix ? 1 : 0)}{m.suffix}</div>
              <Sparkline values={values} />
            </div>
            <Delta value={history.deltas?.[m.field]} polarity={m.polarity} suffix={m.suffix ?? ''} label={`en ${history.points.length} días`} />
          </div>
        );
      })}
    </div>
  );
}

function ResourceDrawer({ r, onClose }: { r: InventoryResource; onClose: () => void }) {
  const { toast, askAgent } = useApp();
  const copy = (text: string, what: string) => navigator.clipboard.writeText(text).then(() => toast(`${what} copiado`));
  const tagValues = r.tagValues ?? {};
  return (
    <Drawer
      title={r.name}
      subtitle={r.type}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={() => copy(r.id, 'ID del recurso')}><Copy size={14} /> Copiar ID</button>
          <button className="btn btn-primary" onClick={() => { askAgent('inventory', `Dame información detallada sobre el recurso ${r.name} del grupo ${r.resourceGroup}.`); onClose(); }}>
            <MessageSquare size={14} /> Preguntar al agente
          </button>
        </>
      }
    >
      <div>
        <div className="subhead">General</div>
        <dl className="kv">
          <dt>Suscripción</dt><dd>{r.subscriptionName}</dd>
          <dt>Grupo de recursos</dt><dd>{r.resourceGroup}</dd>
          <dt>Región</dt><dd>{r.location}</dd>
          <dt>SKU</dt><dd>{r.skuName || '—'}</dd>
          <dt>Estado</dt><dd>{r.provisioningState || '—'}</dd>
          <dt>Custodio</dt><dd>{r.governance.ownerCandidate || <span className="muted">Sin identificar</span>}</dd>
          <dt>Creado</dt><dd>{dateTime(r.createdTime)}</dd>
          <dt>ID</dt><dd className="mono" style={{ fontSize: 12 }}>{r.id}</dd>
        </dl>
      </div>
      <div>
        <div className="spread" style={{ marginBottom: 8 }}>
          <div className="subhead" style={{ margin: 0 }}>Tags obligatorias</div>
          <span className="num secondary" style={{ fontSize: 13 }}>{r.mandatoryTags.present} de {r.mandatoryTags.totalRequired}</span>
        </div>
        <Meter value={r.mandatoryTags.compliancePercentage} tone={complianceTone(r.mandatoryTags.compliancePercentage)} />
        <dl className="kv" style={{ marginTop: 12 }}>
          {Object.entries(tagValues).map(([k, v]) => (
            <Fragment key={k}><dt>{k}</dt><dd className={v ? '' : 'muted'}>{v || 'Falta'}</dd></Fragment>
          ))}
        </dl>
      </div>
      {r.governance.isShadowItCandidate && (
        <Notice tone="warning">
          <strong>Candidato a Shadow IT.</strong> {r.governance.shadowItReason}
        </Notice>
      )}
      <div>
        <div className="subhead">Todas las tags ({Object.keys(r.tags).length})</div>
        {Object.keys(r.tags).length ? (
          <dl className="kv">
            {Object.entries(r.tags).map(([k, v]) => (
              <Fragment key={k}><dt className="mono" style={{ fontSize: 12 }}>{k}</dt><dd>{v}</dd></Fragment>
            ))}
          </dl>
        ) : <span className="muted">El recurso no tiene tags.</span>}
      </div>
    </Drawer>
  );
}

export function InventoryPage() {
  const { scope, scopeKey, toast } = useApp();
  const summary = useApi<InventorySummary>(`inv-summary:${scopeKey}`, () => post('/api/inventory/summary', { subscriptionIds: scope }));
  const tags = useApi<TagCompliance>(`inv-tags:${scopeKey}`, () => post('/api/inventory/tag-compliance', { subscriptionIds: scope }));
  const history = useApi<HistorySeries>(`inv-history:${scopeKey}`, () => post('/api/inventory/history', { subscriptionIds: scope, days: 90 }));

  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [env, setEnv] = useState('');
  const [region, setRegion] = useState('');
  const [onlyNonCompliant, setOnlyNonCompliant] = useState(false);
  const [onlyShadow, setOnlyShadow] = useState(false);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<InventoryResource | null>(null);
  const [dist, setDist] = useState<'type' | 'region' | 'env' | 'sub'>('type');

  useEffect(() => {
    const t = setTimeout(() => { setDebounced(search); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const filters = { search: debounced, environments: env ? [env] : [], locations: region ? [region] : [], onlyNonCompliant, onlyShadowItCandidates: onlyShadow };
  const resources = useApi<Page>(
    `inv-res:${scopeKey}:${JSON.stringify(filters)}:${page}`,
    () => post('/api/inventory/resources', { subscriptionIds: scope, filters, page, pageSize: PAGE_SIZE }),
  );

  const s = summary.data;
  const hasFilters = !!(search || env || region || onlyNonCompliant || onlyShadow);
  const clear = () => { setSearch(''); setEnv(''); setRegion(''); setOnlyNonCompliant(false); setOnlyShadow(false); setPage(1); };

  const exportCsv = () =>
    download('/api/inventory/export', { subscriptionIds: scope, filters }, `inventario_${new Date().toISOString().slice(0, 10)}.csv`)
      .then(() => toast('Inventario exportado'))
      .catch(() => toast('No se pudo exportar el inventario'));

  const distItems = !s ? [] : dist === 'type' ? s.byResourceType : dist === 'region' ? s.byRegion : dist === 'env' ? s.byEnvironment : s.bySubscription;

  return (
    <>
      <PageHeader
        title="Inventario"
        description="Todos los recursos de las suscripciones del alcance, con su cumplimiento de tags y su clasificación de gobernanza, consultados en vivo en Azure Resource Graph."
        actions={<button className="btn" onClick={exportCsv}><Download size={14} /> Exportar CSV</button>}
      />

      {summary.error && !s && <ErrorState error={summary.error} onRetry={summary.reload} />}
      {summary.loading && <Loading label="Consultando Azure Resource Graph…" />}
      {s?.warnings?.length ? <Notice tone="warning">{s.warnings.join(' ')}</Notice> : null}

      {s && (
        <>
          <div className="grid grid-4">
            <StatTile refreshing={summary.refreshing} label="Recursos" value={number(s.totalResources)}
              meta={`${s.totalSubscriptions} suscripciones · ${s.totalResourceGroups} grupos · ${s.totalRegions} regiones`} />
            <StatTile refreshing={summary.refreshing} label="Cumplimiento de tags" value={percent(s.tagCompliancePercentage)}
              meta={`${number(s.nonCompliantResources)} recursos incompletos`} />
            <StatTile refreshing={summary.refreshing} label="Candidatos a Shadow IT" value={number(s.shadowItCandidates)}
              meta="Sin IaC, sin custodio, sin tags y no derivados" />
            <StatTile refreshing={summary.refreshing} label="Sin custodio identificable" value={number(s.resourcesWithoutOwnerCandidate)}
              meta="Sin tag Owner, Team, CreatedBy u otra clave de custodio" />
          </div>

          <div className="grid grid-2">
            <Card title="Tags obligatorias" subtitle="Porcentaje de recursos que tienen cada tag con un valor útil" refreshing={tags.refreshing}>
              <div className="stack">
                {tags.data?.matrix.map((m) => (
                  <div key={m.tag} className="stack" style={{ gap: 6 }}>
                    <div className="spread" style={{ fontSize: 13 }}>
                      <span className="mono">{m.tag}</span>
                      <span className="num secondary">{number(m.present)} de {number(m.present + m.missing)} · <strong className="num">{percent(m.compliancePercentage)}</strong></span>
                    </div>
                    <Meter value={m.compliancePercentage} tone={complianceTone(m.compliancePercentage)} />
                  </div>
                ))}
              </div>
            </Card>
            <Card
              title="Distribución"
              refreshing={summary.refreshing}
              actions={
                <Segmented label="Dimensión" value={dist} onChange={setDist} options={[
                  { id: 'type', label: 'Tipo' }, { id: 'region', label: 'Región' },
                  { id: 'env', label: 'Ambiente' }, { id: 'sub', label: 'Suscripción' },
                ]} />
              }
            >
              <DistributionList items={distItems} />
            </Card>
          </div>

          <Section title="Evolución" description="Un punto por día, registrado cada vez que se consulta el resumen.">
            <TrendRow history={history.data} />
          </Section>
        </>
      )}

      <Section title="Explorador de recursos" description="Búsqueda y filtros resueltos en Azure, no en el navegador.">
        <Card flush refreshing={resources.refreshing}>
          <div className="toolbar" style={{ padding: '0 14px 12px' }}>
            <div className="input-icon grow">
              <Search size={14} />
              <input className="input" placeholder="Buscar por nombre, tipo, grupo o ID" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Buscar recursos" />
            </div>
            <select className="select" value={env} onChange={(e) => { setEnv(e.target.value); setPage(1); }} aria-label="Ambiente">
              <option value="">Todos los ambientes</option>
              {s?.byEnvironment.map((e) => <option key={e.key} value={e.key}>{e.key} ({e.count})</option>)}
            </select>
            <select className="select" value={region} onChange={(e) => { setRegion(e.target.value); setPage(1); }} aria-label="Región">
              <option value="">Todas las regiones</option>
              {s?.byRegion.map((r) => <option key={r.key} value={r.key}>{r.key} ({r.count})</option>)}
            </select>
            <label className="check"><input type="checkbox" checked={onlyNonCompliant} onChange={(e) => { setOnlyNonCompliant(e.target.checked); setPage(1); }} /> Solo no conformes</label>
            <label className="check"><input type="checkbox" checked={onlyShadow} onChange={(e) => { setOnlyShadow(e.target.checked); setPage(1); }} /> Solo Shadow IT</label>
            {hasFilters && <button className="btn btn-ghost btn-sm" onClick={clear}><X size={14} /> Limpiar</button>}
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Recurso</th><th>Tipo</th><th>Suscripción</th><th>Región</th><th>Ambiente</th>
                  <th>Tags</th><th>Gobernanza</th><th />
                </tr>
              </thead>
              <tbody>
                {resources.data?.items.map((r) => (
                  <tr key={r.id}>
                    <td style={{ maxWidth: 280 }}>
                      <span className="primary-cell truncate" style={{ display: 'block' }}>{r.name}</span>
                      <span className="sub truncate">{r.resourceGroup}</span>
                    </td>
                    <td className="secondary">{r.typeDisplayName || shortType(r.type)}</td>
                    <td className="secondary truncate" style={{ maxWidth: 180 }}>{r.subscriptionName}</td>
                    <td className="secondary">{r.location}</td>
                    <td className={r.environment ? '' : 'muted'}>{r.environment || '—'}</td>
                    <td>
                      <StatusBadge ok={r.mandatoryTags.isCompliant} okLabel="Completas" badLabel={`${r.mandatoryTags.present}/${r.mandatoryTags.totalRequired}`} />
                    </td>
                    <td>{r.governance.isShadowItCandidate ? <Badge><span className="dot dot-warning" />Shadow IT</Badge> : <span className="muted">—</span>}</td>
                    <td>
                      <div className="row-actions">
                        <button className="btn btn-ghost btn-sm btn-icon" onClick={() => setSelected(r)} aria-label={`Ver ${r.name}`} title="Ver detalle"><Eye size={14} /></button>
                      </div>
                    </td>
                  </tr>
                ))}
                {resources.data && resources.data.items.length === 0 && (
                  <tr><td colSpan={8} className="table-empty">Ningún recurso coincide con los filtros.</td></tr>
                )}
                {resources.loading && <tr><td colSpan={8}><Loading /></td></tr>}
              </tbody>
            </table>
          </div>
          {resources.data && <Pagination page={page} pageSize={PAGE_SIZE} total={resources.data.total} onPage={setPage} />}
        </Card>
      </Section>

      {selected && <ResourceDrawer r={selected} onClose={() => setSelected(null)} />}
    </>
  );
}

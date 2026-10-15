import { useState } from 'react';
import { Download } from 'lucide-react';
import { download, get } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, money, number } from '../../lib/format';
import type { CountBy, InventoryReport as Reporte, InventoryReportProvider } from '../../lib/types';
import { useApp } from '../../state/hooks';
import { Card, ErrorState, Loading, Notice, Section, StatTile } from '../../components/ui';

/**
 * Inventario de todas las nubes conectadas, por cuenta, tipo y región. Lo deja
 * calculado el recolector diario: abrirlo no consulta la nube ni despierta la base.
 */
export function InventoryReport() {
  const { toast } = useApp();
  const { data, error, loading, refreshing, reload } = useApi<Reporte>('inventory-report', () => get('/api/inventory/report'));
  const [exporting, setExporting] = useState(false);

  async function exportar() {
    setExporting(true);
    try {
      await download('/api/inventory/report/export', undefined, 'inventario-multinube.csv');
    } catch (e) {
      toast(`No se pudo exportar: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setExporting(false);
    }
  }

  if (loading) return <Loading label="Preparando el inventario…" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  if (!data.providers.length) return <Notice>El recolector diario todavía no registró recursos.</Notice>;

  return (
    <Section
      title="Inventario multinube"
      description={`Lo que hay en cada nube según la última recolección diaria. Gasto de los últimos ${data.cost_days} días con datos.`}
      actions={<button className="btn btn-sm" onClick={exportar} disabled={exporting}><Download size={14} /> {exporting ? 'Exportando…' : 'Exportar CSV'}</button>}
    >
      <div className="stack" style={{ gap: 16 }}>
        {data.providers.map((p) => <Nube key={p.name} p={p} refreshing={refreshing} />)}
        <Card title="Por cuenta" flush refreshing={refreshing}>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Cuenta</th><th>Nube</th><th className="num">Recursos</th><th className="num">Gasto</th><th className="num">Hallazgos</th><th>Tipos principales</th></tr></thead>
              <tbody>
                {data.accounts.map((c) => (
                  <tr key={c.uid}>
                    <td><span className="primary-cell">{c.name}</span><span className="sub mono">{c.native_id}</span></td>
                    <td className="secondary">{data.providers.find((p) => p.name === c.provider)?.label ?? c.provider}</td>
                    <td className="num">{number(c.resources)}</td>
                    <td className="num">{c.cost_30d === null ? <span className="muted" title="Sin dato de costos para esta cuenta">—</span> : money(c.cost_30d, c.currency ?? 'USD')}</td>
                    <td className="num">{c.open_findings ? number(c.open_findings) : <span className="muted">0</span>}</td>
                    <td className="secondary">{c.by_type.slice(0, 3).map((t) => `${t.key} (${t.count})`).join(', ') || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </Section>
  );
}

function Nube({ p, refreshing }: { p: InventoryReportProvider; refreshing: boolean }) {
  return (
    <Card title={p.label} subtitle={p.inventory_at ? `Recolección del ${dateTime(p.inventory_at)}` : undefined} refreshing={refreshing}>
      <div className="stack" style={{ gap: 16 }}>
        <div className="grid grid-4">
          <StatTile label="Recursos" value={number(p.resources)} meta={`${number(p.accounts)} cuenta(s)`} />
          <StatTile label="Gasto" value={p.cost_30d === null ? '—' : money(p.cost_30d, p.currency ?? 'USD')}
            meta={p.cost_30d === null ? 'Costos aún no conectados: no es cero' : 'Facturado'} />
          <StatTile label="Hallazgos activos" value={number(p.open_findings)} />
          <StatTile label="En Terraform" value={p.iac_known ? number(p.in_iac) : '—'}
            meta={p.iac_known ? `de ${number(p.resources)}` : 'Sin estados de Terraform conectados'} />
        </div>
        <div className="grid grid-2">
          <Conteo titulo="Por tipo" items={p.by_type} />
          <Conteo titulo="Por región" items={p.by_region} />
        </div>
      </div>
    </Card>
  );
}

function Conteo({ titulo, items }: { titulo: string; items: CountBy[] }) {
  return (
    <div>
      <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>{titulo}</div>
      {items.map((i, n) => (
        <div key={i.key} className="spread" style={{ padding: '6px 0', borderTop: n ? '1px solid var(--border)' : 0, fontSize: 13 }}>
          <span className="mono">{i.key}</span>
          <strong className="num">{number(i.count)}</strong>
        </div>
      ))}
    </div>
  );
}

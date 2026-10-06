import { useState } from 'react';
import { Download } from 'lucide-react';
import { get, downloadUrl } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { number } from '../../lib/format';
import type { IsoReport } from '../../lib/types';
import { Card, Empty, ErrorState, Loading, PageHeader, Section, Segmented, StatTile } from '../../components/ui';

const CLASS_DOT: Record<string, string> = {
  Confidencial: 'dot-critical',
  Restringido: 'dot-serious',
  'Uso Interno': 'dot-accent',
};

export function IsoPage() {
  const { data, error, loading, refreshing, reload } = useApi<IsoReport>('iso', () => get('/api/governance/iso'));
  const [filter, setFilter] = useState<string>('all');

  const stats = data?.stats ?? {};
  const classes = Object.keys(stats.classification_distribution ?? {});
  const rows = (data?.data ?? []).filter((a) => filter === 'all' || a['Clasificación del activo'] === filter);

  return (
    <>
      <PageHeader
        title="Cumplimiento ISO 27001"
        description="Inventario de activos de información con su triada de confidencialidad, integridad y disponibilidad, conforme a los controles 5.9, 5.12 y 5.13 de ISO/IEC 27001:2022."
        actions={<a className="btn" href={downloadUrl('Azure_IaC_Inventario.xlsx')}><Download size={14} /> Excel maestro</a>}
      />
      {loading && <Loading />}
      {error && !data && <ErrorState error={error} onRetry={reload} />}
      {data && (data.error || !data.data.length) ? (
        <Card>
          <Empty title="Sin clasificación todavía">
            <span>{data.error ?? 'La hoja ISO está vacía.'} Ejecuta <strong>Sincronizar</strong> para correr el pipeline de inventario, que clasifica cada activo.</span>
          </Empty>
        </Card>
      ) : data && (
        <>
          <div className="grid grid-4">
            <StatTile refreshing={refreshing} label="Activos clasificados" value={number(stats.total_assets ?? 0)} />
            <StatTile refreshing={refreshing} icon={<span className="dot dot-critical" />} label="Confidenciales" value={number(stats.classification_distribution?.Confidencial ?? 0)} />
            <StatTile refreshing={refreshing} label="Requieren análisis de riesgo" value={number(stats.risk_management_distribution?.SI ?? 0)} />
            <StatTile refreshing={refreshing} label="Criticidad promedio" value={number(stats.average_criticality_score ?? 0, 1)} unit="de 9" />
          </div>
          <Section
            title="Activos"
            actions={classes.length > 1 ? (
              <Segmented label="Clasificación" value={filter} onChange={setFilter}
                options={[{ id: 'all', label: 'Todos' }, ...classes.map((c) => ({ id: c, label: c }))]} />
            ) : undefined}
          >
            <Card flush refreshing={refreshing}>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr><th>Activo</th><th>Clasificación</th><th>Custodio</th><th className="center">C · I · D</th><th className="num">Criticidad</th><th>Análisis de riesgo</th></tr>
                  </thead>
                  <tbody>
                    {rows.map((a, i) => (
                      <tr key={`${a.name}-${i}`}>
                        <td><span className="primary-cell">{a.name}</span><span className="sub">{a.resourceType}{a.subscription ? ` · ${a.subscription}` : ''}</span></td>
                        <td><span className="badge"><span className={`dot ${CLASS_DOT[a['Clasificación del activo']] ?? ''}`} />{a['Clasificación del activo']}</span></td>
                        <td className="secondary">{a.custodio || '—'}</td>
                        <td className="center mono">{a.confidencialidad} · {a.integridad} · {a.disponibilidad}</td>
                        <td className="num primary-cell">{a['puntuación del activo']}</td>
                        <td>{a['Gestión de riesgo (SI/NO)'] === 'SI' ? <span className="badge"><span className="dot dot-serious" />Requerido</span> : <span className="muted">No</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </Section>
        </>
      )}
    </>
  );
}

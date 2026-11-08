import { useState } from 'react';
import { get } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, number } from '../../lib/format';
import type { Severity } from '../../lib/types';
import { Card, Empty, ErrorState, Loading, Section, Segmented, SeverityBadge } from '../../components/ui';

interface Tramo { title: string; severity: Severity; category: string; namespace: string | null; resource: string; desde: string | null; hasta: string | null; minutes: number | null }
interface Historial { cluster: string; days: number; open: Tramo[]; closed: Tramo[]; median_minutes: number | null }

function duracion(min: number | null): string {
  if (min === null) return '—';
  if (min < 60) return `${min} min`;
  return min < 1440 ? `${number(min / 60, 1)} h` : `${number(min / 1440, 1)} d`;
}

/** Historial de incidencias del clúster: cuándo empezó y terminó cada una (lo lleva k8s-watch cada 10 minutos). */
export function K8sHistory({ nombre }: { nombre: string }) {
  const [dias, setDias] = useState<'7' | '30' | '90'>('30');
  const { data, error, loading, reload } = useApi<Historial>(`k8s-historial-${nombre}-${dias}`,
    () => get(`/api/activos/kubernetes/${encodeURIComponent(nombre)}/historial?dias=${dias}`));
  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  const filas = [...data.open, ...data.closed];

  return (
    <Section title="Historial de incidencias"
      description={`${number(data.open.length)} abierta(s) ahora · ${number(data.closed.length)} cerrada(s) en ${dias} días${data.median_minutes !== null ? ` · mediana de duración ${duracion(data.median_minutes)}` : ''}. Precisión de unos 10 minutos.`}
      actions={<Segmented label="Periodo del historial" value={dias} onChange={setDias} options={[{ id: '7', label: '7 días' }, { id: '30', label: '30 días' }, { id: '90', label: '90 días' }]} />}>
      <Card flush>
        {filas.length ? (
          <div className="table-wrap" style={{ maxHeight: 420, overflowY: 'auto' }}>
            <table className="table">
              <thead><tr><th>Severidad</th><th>Incidencia</th><th>Namespace</th><th>Inicio</th><th>Fin</th><th className="num">Duración</th></tr></thead>
              <tbody>
                {filas.map((t, n) => (
                  <tr key={`${t.resource}-${t.desde}-${n}`}>
                    <td><SeverityBadge severity={t.severity} /></td>
                    <td>{t.title}</td>
                    <td className="mono secondary" style={{ fontSize: 12 }}>{t.namespace ?? '—'}</td>
                    <td className="secondary" style={{ whiteSpace: 'nowrap' }}>{t.desde ? dateTime(t.desde) : '—'}</td>
                    <td className="secondary" style={{ whiteSpace: 'nowrap' }}>{t.hasta ? dateTime(t.hasta) : <strong>Abierta</strong>}</td>
                    <td className="num">{duracion(t.minutes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty title="Sin historial todavía">Se llena desde que k8s-watch empieza a llevarlo (cada 10 minutos).</Empty>}
      </Card>
    </Section>
  );
}

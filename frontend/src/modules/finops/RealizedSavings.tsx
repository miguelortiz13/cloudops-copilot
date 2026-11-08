import { get } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, money, number } from '../../lib/format';
import { Card, Empty, Section, StatTile } from '../../components/ui';

interface Realizado {
  days: number;
  applied: { id: number; name: string; category: string; expected_monthly: number; applied_by: string; applied_at: string;
    status: 'pendiente' | 'verificado'; removed_at: string | null; realized_monthly: number | null }[];
  removed: { uid: string; name: string; provider: string; type: string; removed_at: string; monthly_before: number }[];
  totals: { applied_pending: number; expected_monthly: number; realized_monthly: number; removed_monthly: number };
}

/**
 * Ahorro realizado (fase 4 del plan 10): lo que de verdad se dejó de gastar. Una oportunidad aplicada se verifica
 * cuando el recurso desaparece del inventario; su ahorro es el gasto real de sus 30 días previos.
 */
export function RealizedSavings({ version }: { version: number }) {
  const { data } = useApi<Realizado>(`costos-ahorro-realizado-${version}`, () => get('/api/costos/ahorro/realizado?dias=90'));
  if (!data) return null;
  const t = data.totals;
  return (
    <Section title="Ahorro realizado" description="Medido, no estimado: el gasto real de los 30 días previos a la baja de cada recurso. Últimos 90 días.">
      <div className="stack" style={{ gap: 16 }}>
        <div className="grid grid-4">
          <StatTile label="Realizado (aplicadas)" value={money(t.realized_monthly, 'USD', 2)} unit="/ mes" meta={`Se esperaba ${money(t.expected_monthly, 'USD', 2)}`} />
          <StatTile label="Aplicadas pendientes" value={number(t.applied_pending)} meta="El recurso sigue en el inventario" />
          <StatTile label="Gasto evitado por bajas" value={money(t.removed_monthly, 'USD', 2)} unit="/ mes" meta={`${number(data.removed.length)} recurso(s) dados de baja`} />
          <StatTile label="Oportunidades aplicadas" value={number(data.applied.length)} />
        </div>
        <Card flush>
          {data.applied.length ? (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Recurso</th><th>Categoría</th><th>Aplicada</th><th className="num">Esperado</th><th className="num">Realizado</th></tr></thead>
                <tbody>
                  {data.applied.map((a) => (
                    <tr key={a.id}>
                      <td>{a.name}</td>
                      <td className="secondary">{a.category}</td>
                      <td className="secondary">{dateTime(a.applied_at)} · {a.applied_by}</td>
                      <td className="num">{money(a.expected_monthly, 'USD', 2)}</td>
                      <td className="num">{a.status === 'verificado' ? money(a.realized_monthly ?? 0, 'USD', 2) : <span className="secondary">Pendiente</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty>Ninguna oportunidad marcada como aplicada todavía: márcalas en la tabla de recursos sin uso.</Empty>}
        </Card>
      </div>
    </Section>
  );
}

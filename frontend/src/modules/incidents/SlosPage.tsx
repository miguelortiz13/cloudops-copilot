import { get } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { number } from '../../lib/format';
import { Card, Empty, ErrorState, Loading, Meter, Notice, PageHeader } from '../../components/ui';

interface Slo {
  url: string; samples: number; failures: number; availability_pct: number | null; budget_consumed_pct: number | null;
  budget_remaining_pct: number | null; burn_1h: number | null; burn_6h: number | null; burning: boolean; met: boolean | null;
}
interface Estado { objective_pct: number; window_days: number; items: Slo[] }

const tono = (restante: number) => (restante > 50 ? 'good' : restante > 0 ? 'warning' : 'critical');

/**
 * Operación → SLOs (fase 7.3, plan 12): disponibilidad de cada URL de los chequeos contra su objetivo, el presupuesto
 * de error que queda y su quema. Quemar 14,4× en 1 h y 6× en 6 h abre un incidente SLOBurnRate.
 */
export function SlosPage() {
  const { data, error, loading, reload } = useApi<Estado>('operacion-slos', () => get('/api/operacion/slos'));
  return (
    <>
      <PageHeader title="SLOs" description="Disponibilidad de cada servicio con chequeo HTTP contra su objetivo, el presupuesto de error que queda y qué tan rápido se gasta. El objetivo, la ventana y las URLs se cambian en Plataforma → Ajustes → Chequeos HTTP." />
      {loading && !data ? <Loading /> : error && !data ? <ErrorState error={error} onRetry={reload} /> : data && (
        <div className="stack" style={{ gap: 16 }}>
          <Notice>Objetivo {number(data.objective_pct, 2)} % en {data.window_days} días: el presupuesto de error es el {number(100 - data.objective_pct, 2)} % de los chequeos. Una quema de 1× lo gasta justo en la ventana; 14,4× en la última hora y 6× en 6 horas abren un incidente.</Notice>
          {data.items.length === 0 ? <Card><Empty title="Sin servicios con SLO">Agrega una URL en Plataforma → Ajustes → Chequeos HTTP: cada una tiene su SLO.</Empty></Card> : (
            <Card flush>
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Servicio</th><th className="num">Disponibilidad</th><th style={{ width: 220 }}>Presupuesto de error restante</th><th className="num">Quema 1 h</th><th className="num">Quema 6 h</th><th>Estado</th></tr></thead>
                  <tbody>
                    {data.items.map((s) => (
                      <tr key={s.url}>
                        <td><span className="mono" style={{ fontSize: 12, wordBreak: 'break-all' }}>{s.url}</span><span className="sub">{number(s.samples)} chequeos, {number(s.failures)} fallidos</span></td>
                        <td className="num">{s.availability_pct === null ? '—' : `${number(s.availability_pct, 2)} %`}</td>
                        <td>{s.budget_remaining_pct === null ? <span className="secondary">Sin datos todavía</span> : (
                          <div className="stack" style={{ gap: 4 }}>
                            <Meter value={s.budget_remaining_pct} tone={tono(s.budget_remaining_pct)} />
                            <span className="secondary" style={{ fontSize: 12 }}>{number(s.budget_remaining_pct, 1)} %</span>
                          </div>
                        )}</td>
                        <td className="num">{s.burn_1h === null ? '—' : `${number(s.burn_1h, 1)}×`}</td>
                        <td className="num">{s.burn_6h === null ? '—' : `${number(s.burn_6h, 1)}×`}</td>
                        <td>{s.met === null ? <span className="secondary">—</span> : (
                          <span className="badge"><span className={`dot ${s.burning ? 'dot-critical' : s.met ? 'dot-good' : 'dot-warning'}`} aria-hidden="true" />
                            {s.burning ? 'Quemando el presupuesto' : s.met ? 'En objetivo' : 'Fuera de objetivo'}</span>
                        )}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </div>
      )}
    </>
  );
}

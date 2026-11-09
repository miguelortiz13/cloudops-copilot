import { get } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, percent } from '../../lib/format';
import { Card, Empty, Section } from '../../components/ui';

interface Suite { suite: string; cases: number; passed: number; accuracy: number | null; target: number; invented_numbers: number }
interface Corrida { at: string; model: string; run: string; suites: Suite[] }

const NOMBRE: Record<string, string> = { asistente: 'Asistente (chat)', incidentes: 'Diagnóstico de incidentes', dominios: 'IA de los dominios', inyeccion: 'Resistencia a prompt injection', recuperacion: 'Recuperación de conocimiento (recall@5)' };

/** Evals semanales (plan 11, hito IA-1): la última corrida por suite contra el objetivo y la tendencia. */
export function EvalsSection() {
  const { data } = useApi<{ runs: Corrida[] }>('ia-evals', () => get('/api/ia/evals?limite=8'));
  const runs = data?.runs ?? [];
  const ultima = runs[0];
  return (
    <Section title="Evals" description="Corrida semanal con el modelo real (lunes 07:00 UTC, GitHub Actions): casos por suite, objetivo de 90 % y cero cifras inventadas.">
      <Card flush>
        {!ultima ? <Empty title="Sin corridas todavía">La primera llega con el workflow semanal de evals.</Empty> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Suite</th><th className="num">Correctos</th><th>Exactitud</th><th className="num">Cifras inventadas</th><th>Tendencia (más reciente primero)</th></tr></thead>
              <tbody>
                {ultima.suites.map((s) => {
                  const ok = (s.accuracy ?? 0) >= s.target && s.invented_numbers === 0;
                  const historia = runs.map((r) => r.suites.find((x) => x.suite === s.suite)?.accuracy).filter((a): a is number => a != null);
                  return (
                    <tr key={s.suite}>
                      <td>{NOMBRE[s.suite] ?? s.suite}</td>
                      <td className="num">{s.passed}/{s.cases}</td>
                      <td><span className="badge"><span className={`dot ${ok ? 'dot-good' : 'dot-critical'}`} aria-hidden="true" />{s.accuracy === null ? '—' : percent(s.accuracy * 100, 0)} · objetivo {percent(s.target * 100, 0)}</span></td>
                      <td className="num">{s.invented_numbers}</td>
                      <td className="secondary">{historia.map((a) => percent(a * 100, 0)).join(' · ')}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {ultima && <p className="secondary" style={{ fontSize: 12, marginTop: 8 }}>Última corrida: {dateTime(ultima.at)} · {ultima.model}</p>}
    </Section>
  );
}

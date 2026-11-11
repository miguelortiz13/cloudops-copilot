import { get } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, money, number } from '../../lib/format';
import { Sparkline } from '../../components/charts';
import { Card, Delta, Empty, Loading, Section, StatTile } from '../../components/ui';

interface Incidentes { total: number; mtta_min: number | null; mttr_min: number | null; noise_pct: number | null; marked_pct: number | null; correct_pct: number | null }
interface Semana { week: string; start: string; incidents: Incidentes; findings: { detected: number; resolved: number; days_to_close: number | null } }
interface Valor {
  configured: boolean; weeks: Semana[]; findings_open: number;
  savings: { realized_monthly: number; expected_monthly: number; applied_pending: number };
  evals: { at: string; suites: { suite: string; accuracy: number | null; target: number }[]; on_target: number } | null;
}

type Polaridad = 'up-good' | 'up-bad';
const minutos = (v: number | null) => (v === null ? '—' : v < 120 ? `${number(v, 0)} min` : `${number(v / 60, 1)} h`);
const pct = (v: number | null) => (v === null ? '—' : `${number(v, 0)} %`);

/** Un indicador: la última semana cerrada, el cambio contra la anterior y la tendencia de las semanas cerradas. */
function Indicador({ label, semanas, valor, formato, unidad, polaridad, meta }: {
  label: string; semanas: Semana[]; valor: (s: Semana) => number | null; formato: (v: number | null) => string;
  unidad: string; polaridad: Polaridad; meta?: string;
}) {
  const serie = semanas.map(valor);
  const [prev, ult] = serie.slice(-2);
  const conDatos = serie.filter((v): v is number => v !== null);
  return (
    <StatTile label={label} value={formato(ult ?? null)}
      delta={ult != null && prev != null ? <Delta value={ult - prev} polarity={polaridad} suffix={unidad} label="vs. semana anterior" /> : undefined}
      meta={<>{conDatos.length >= 2 && <Sparkline values={conDatos} width={90} height={22} />}{meta && <span> {meta}</span>}</>} />
  );
}

/**
 * Tablero de valor (fase 7.2, plan 12): si la operación mejora, con números de producción. Cada indicador es la
 * última semana cerrada contra la anterior, con la tendencia de las cerradas; la semana en curso no se compara.
 */
export function ValorSection() {
  const { data, loading } = useApi<Valor>('inicio-valor', () => get('/api/inicio/valor?semanas=8'));
  if (loading && !data) return <Section title="Valor de la operación"><Card><Loading /></Card></Section>;
  if (!data?.configured) return null;
  const cerradas = data.weeks.slice(0, -1);
  const ult = cerradas[cerradas.length - 1];
  const sinMarcas = ult && (ult.incidents.marked_pct ?? 100) < 50;
  return (
    <Section title="Valor de la operación" description={ult ? `Semana ${ult.week} (cerrada) contra la anterior, y la tendencia de ${cerradas.length} semanas.` : undefined}>
      {!ult || data.weeks.every((s) => s.incidents.total === 0 && s.findings.resolved === 0) ? <Card><Empty>Todavía sin datos para medir.</Empty></Card> : (
        <div className="grid grid-4">
          <Indicador label="Tiempo hasta reconocer" semanas={cerradas} valor={(s) => s.incidents.mtta_min} formato={minutos} unidad=" min" polaridad="up-bad" meta="mediana" />
          <Indicador label="Tiempo hasta resolver" semanas={cerradas} valor={(s) => s.incidents.mttr_min} formato={minutos} unidad=" min" polaridad="up-bad" meta="mediana" />
          <Indicador label="Incidentes que eran ruido" semanas={cerradas} valor={(s) => s.incidents.noise_pct} formato={pct} unidad=" pp" polaridad="up-bad"
            meta={`${number(ult.incidents.total)} incidente(s)`} />
          <Indicador label="Diagnósticos correctos" semanas={cerradas} valor={(s) => s.incidents.correct_pct} formato={pct} unidad=" pp" polaridad="up-good"
            meta={`marcados ${pct(ult.incidents.marked_pct)}${sinMarcas ? ': faltan marcas' : ''}`} />
          <Indicador label="Hallazgos graves resueltos" semanas={cerradas} valor={(s) => s.findings.resolved} formato={(v) => (v === null ? '—' : number(v))} unidad=""
            polaridad="up-good" meta={`${number(data.findings_open)} abiertos hoy${ult.findings.days_to_close != null ? ` · ${number(ult.findings.days_to_close, 1)} días para cerrar` : ''}`} />
          <StatTile label="Ahorro realizado" value={money(data.savings.realized_monthly, 'USD', 2)} unit="/ mes"
            meta={`esperado ${money(data.savings.expected_monthly, 'USD', 2)} · ${number(data.savings.applied_pending)} por verificar`} />
          <StatTile label="Evals de la IA" value={data.evals ? `${data.evals.on_target}/${data.evals.suites.length}` : '—'} unit="en objetivo"
            meta={data.evals ? `corrida del ${dateTime(data.evals.at)}` : 'sin corridas'} />
        </div>
      )}
    </Section>
  );
}

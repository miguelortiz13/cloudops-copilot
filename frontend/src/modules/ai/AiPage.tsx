import { useState } from 'react';
import { get } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, money, number, percent } from '../../lib/format';
import { EvalsSection } from './EvalsSection';
import { McpSection } from './McpSection';
import { ConocimientoSection } from './ConocimientoSection';
import { Card, Drawer, Empty, ErrorState, Loading, Notice, PageHeader, Section, Segmented, StatTile } from '../../components/ui';

interface Bloque { calls: number; errors: number; input_tokens: number; output_tokens: number; cost_usd: number; p50_ms: number | null; p95_ms: number | null }
interface Resumen { days: number; total: Bloque; by_domain: Record<string, Bloque>; by_use: Record<string, Bloque>; tools: { name: string; calls: number; errors: number }[]; priced: boolean; mcp?: { calls: number; errors: number } }
interface Span { name: string; duration_ms: number; attributes: Record<string, unknown> }
interface Traza { trace_id: string; name: string; start: string; duration_ms: number; attributes: Record<string, unknown>; spans: Span[] | number }

const DOMINIO: Record<string, string> = {
  inicio: 'Inicio', activos: 'Activos', costos: 'Costos', riesgo: 'Riesgo', operacion: 'Operación', plataforma: 'Plataforma',
};
const ms = (v: number | null) => (v === null ? '—' : v < 1000 ? `${v} ms` : `${number(v / 1000, 1)} s`);

function Tabla({ filas, etiqueta, priced }: { filas: Record<string, Bloque>; etiqueta: (k: string) => string; priced: boolean }) {
  const claves = Object.keys(filas).sort((a, b) => filas[b].calls - filas[a].calls);
  return (
    <div className="table-wrap">
      <table className="table">
        <thead><tr><th>Uso</th><th className="num">Llamadas</th><th className="num">Errores</th><th className="num">Tokens (entrada / salida)</th><th className="num">Costo</th><th className="num">p50</th><th className="num">p95</th></tr></thead>
        <tbody>
          {claves.map((k) => {
            const b = filas[k];
            return (
              <tr key={k}>
                <td>{etiqueta(k)}</td>
                <td className="num">{number(b.calls)}</td>
                <td className="num">{number(b.errors)}</td>
                <td className="num">{number(b.input_tokens)} / {number(b.output_tokens)}</td>
                <td className="num">{priced ? money(b.cost_usd, 'USD', 4) : '—'}</td>
                <td className="num">{ms(b.p50_ms)}</td>
                <td className="num">{ms(b.p95_ms)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Plataforma → IA (plan 11, hito IA-1): qué hizo el modelo, cuánto costó y cuánto tardó, por dominio y por uso,
 * con cada traza (turnos del modelo y herramientas) a un clic.
 */
export function AiPage() {
  const [dias, setDias] = useState<'1' | '7' | '30'>('7');
  const [abierta, setAbierta] = useState<string | null>(null);
  const r = useApi<Resumen>(`ia-resumen-${dias}`, () => get(`/api/ia/resumen?dias=${dias}`));
  const t = useApi<{ items: Traza[]; total: number }>(`ia-trazas-${dias}`, () => get(`/api/ia/trazas?dias=${dias}&limite=50`));
  if (r.loading && !r.data) return <Loading />;
  if (r.error && !r.data) return <ErrorState error={r.error} onRetry={r.reload} />;
  if (!r.data) return null;
  const d = r.data;

  return (
    <>
      <PageHeader title="IA" description="Qué hizo el modelo en cada dominio, cuánto costó y cuánto tardó. Cada respuesta deja una traza con sus turnos y las herramientas que consultó; no se guarda el texto de las preguntas ni de las respuestas." />
      <div className="stack" style={{ gap: 24 }}>
        <div className="toolbar"><Segmented label="Periodo" value={dias} onChange={setDias} options={[{ id: '1', label: '24 horas' }, { id: '7', label: '7 días' }, { id: '30', label: '30 días' }]} /></div>
        {!d.priced && <Notice>El costo no se estima hasta configurar el precio del modelo por millón de tokens en <em>Plataforma → Ajustes → Inteligencia artificial</em>.</Notice>}
        <div className="grid grid-4">
          <StatTile label="Llamadas al modelo" value={number(d.total.calls)} meta={`En ${dias === '1' ? 'el último día' : `${dias} días`}`} />
          <StatTile label="Errores" value={number(d.total.errors)} meta={d.total.calls ? `${percent((d.total.errors / d.total.calls) * 100, 1)} de las llamadas` : undefined} />
          <StatTile label="Costo estimado" value={d.priced ? money(d.total.cost_usd, 'USD', 2) : '—'} meta={`${number(d.total.input_tokens + d.total.output_tokens)} tokens`} />
          <StatTile label="Latencia p95" value={ms(d.total.p95_ms)} meta={`p50 ${ms(d.total.p50_ms)}`} />
        </div>
        <EvalsSection />
        <McpSection llamadas={d.mcp} />
        <ConocimientoSection />
        {d.total.calls === 0 ? <Card><Empty title="Sin llamadas al modelo en este periodo">Las trazas empiezan con esta versión: aparecen con la próxima pregunta, diagnóstico o explicación.</Empty></Card> : (
          <>
            <Section title="Por dominio"><Card flush><Tabla filas={d.by_domain} etiqueta={(k) => DOMINIO[k] ?? k} priced={d.priced} /></Card></Section>
            <div className="grid grid-2">
              <Section title="Por uso"><Card flush><Tabla filas={d.by_use} etiqueta={(k) => k} priced={d.priced} /></Card></Section>
              <Section title="Herramientas más usadas">
                <Card flush>
                  <div className="table-wrap">
                    <table className="table">
                      <thead><tr><th>Herramienta</th><th className="num">Llamadas</th><th className="num">Con error</th></tr></thead>
                      <tbody>{d.tools.map((h) => <tr key={h.name}><td className="mono" style={{ fontSize: 12 }}>{h.name}</td><td className="num">{number(h.calls)}</td><td className="num">{number(h.errors)}</td></tr>)}</tbody>
                    </table>
                  </div>
                </Card>
              </Section>
            </div>
            <Section title="Trazas recientes" description={t.data ? `${number(Math.min(t.data.total, 50))} de ${number(t.data.total)}` : undefined}>
              <Card flush>
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>Cuándo</th><th>Uso</th><th className="num">Duración</th><th className="num">Tokens</th><th>Resultado</th></tr></thead>
                    <tbody>
                      {(t.data?.items ?? []).map((x) => (
                        <tr key={x.trace_id}>
                          <td className="secondary" style={{ whiteSpace: 'nowrap' }}><button className="btn btn-ghost btn-sm" onClick={() => setAbierta(x.trace_id)}>{dateTime(x.start)}</button></td>
                          <td className="mono" style={{ fontSize: 12 }}>{String(x.attributes['cloudops.use'])}</td>
                          <td className="num">{ms(x.duration_ms)}</td>
                          <td className="num">{number(Number(x.attributes['gen_ai.usage.input_tokens']) + Number(x.attributes['gen_ai.usage.output_tokens']))}</td>
                          <td>{x.attributes['error.type'] ? <span className="badge"><span className="dot dot-critical" aria-hidden="true" />Error</span> : <span className="secondary">{String(x.spans)} paso(s)</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            </Section>
          </>
        )}
      </div>
      {abierta && <DetalleTraza id={abierta} onClose={() => setAbierta(null)} />}
    </>
  );
}

function DetalleTraza({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, error, loading } = useApi<Traza>(`ia-traza-${id}`, () => get(`/api/ia/trazas/${id}`));
  return (
    <Drawer title="Traza" subtitle={<span className="mono" style={{ fontSize: 12 }}>{id}</span>} onClose={onClose}>
      {loading && <Loading />}
      {error && <Notice tone="critical">{error}</Notice>}
      {data && Array.isArray(data.spans) && (
        <div className="stack" style={{ gap: 12 }}>
          <p style={{ margin: 0, fontSize: 13 }}><strong>{data.name}</strong> · {ms(data.duration_ms)} · {String(data.attributes['gen_ai.request.model'])}</p>
          {data.attributes['error.type'] ? <Notice tone="critical">{String(data.attributes['error.type'])}</Notice> : null}
          <ol className="timeline">
            {data.spans.map((s, n) => (
              <li key={n}>
                <div><strong>{s.name}</strong> · {ms(s.duration_ms)}</div>
                <div className="when">
                  {s.attributes['gen_ai.operation.name'] === 'chat'
                    ? `${number(Number(s.attributes['gen_ai.usage.input_tokens']))} tokens de entrada, ${number(Number(s.attributes['gen_ai.usage.output_tokens']))} de salida, ${String(s.attributes['cloudops.tool_calls'])} herramienta(s) pedidas`
                    : `${JSON.stringify(s.attributes['cloudops.tool.arguments'])} → ${number(Number(s.attributes['cloudops.tool.result_chars']))} caracteres`}
                </div>
                {s.attributes['error.type'] ? <div className="secondary" style={{ marginTop: 2 }}>Error: {String(s.attributes['error.type'])}</div> : null}
              </li>
            ))}
          </ol>
        </div>
      )}
    </Drawer>
  );
}

/**
 * Tendencia histórica de los KPIs de gobernanza.
 *
 * La forma elegida es una fila de stat tiles (valor + delta + sparkline) y no un
 * gráfico: los datos son un puñado de números de cabecera con su evolución, que
 * es justo el caso en que un gráfico estorba más de lo que aporta.
 *
 * El color del delta depende de la polaridad de cada métrica: subir el
 * cumplimiento de tags es bueno, subir el Shadow IT es malo, y el total de
 * recursos no es ni bueno ni malo. Pintar todo "verde si sube" sería un error de
 * lectura. El sentido nunca queda sólo en el color: siempre va acompañado de una
 * flecha y del signo.
 */

export interface HistoryPoint {
  date: string;
  totalResources?: number;
  nonCompliantResources?: number;
  tagCompliancePercentage?: number;
  shadowItCandidates?: number;
  resourcesWithoutOwnerCandidate?: number;
}

export interface HistorySeries {
  points: HistoryPoint[];
  available: boolean;
  pointCount?: number;
  firstDate?: string | null;
  lastDate?: string | null;
  deltas: Record<string, number>;
}

/** Polaridad: qué significa que la métrica suba. */
type Polarity = 'up-good' | 'up-bad' | 'neutral';

const METRICAS: {
  field: keyof HistoryPoint;
  label: string;
  polarity: Polarity;
  suffix?: string;
}[] = [
  { field: 'tagCompliancePercentage', label: 'Cumplimiento de tags', polarity: 'up-good', suffix: '%' },
  { field: 'nonCompliantResources', label: 'Recursos no conformes', polarity: 'up-bad' },
  { field: 'shadowItCandidates', label: 'Candidatos a Shadow IT', polarity: 'up-bad' },
  { field: 'totalResources', label: 'Recursos totales', polarity: 'neutral' },
];

function formatearValor(valor: number | undefined, suffix?: string): string {
  if (valor === undefined || valor === null) return '—';
  const texto = Number.isInteger(valor) ? valor.toLocaleString('es-CO') : valor.toFixed(1);
  return suffix ? `${texto}${suffix}` : texto;
}

function colorDelta(delta: number, polarity: Polarity): string {
  if (delta === 0 || polarity === 'neutral') return 'var(--text-secondary)';
  const esMejora = polarity === 'up-good' ? delta > 0 : delta < 0;
  return esMejora ? 'var(--success)' : 'var(--danger)';
}

/**
 * Sparkline de una sola serie: traza gris de contexto y el punto actual en el
 * color de acento. Al ser una sola serie no lleva leyenda — el título del tile
 * ya la nombra.
 */
function Sparkline({
  valores,
  fechas,
  suffix,
}: {
  valores: number[];
  fechas: string[];
  suffix?: string;
}) {
  if (valores.length < 2) return null;

  const ancho = 120;
  const alto = 28;
  const margen = 4;
  const min = Math.min(...valores);
  const max = Math.max(...valores);
  const rango = max - min || 1;

  const puntos = valores.map((v, i) => {
    const x = margen + (i / (valores.length - 1)) * (ancho - margen * 2);
    const y = alto - margen - ((v - min) / rango) * (alto - margen * 2);
    return { x, y, v, fecha: fechas[i] };
  });

  const d = puntos.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  const ultimo = puntos[puntos.length - 1];

  return (
    <svg
      width={ancho}
      height={alto}
      viewBox={`0 0 ${ancho} ${alto}`}
      role="img"
      aria-label={`Evolución de ${valores.length} puntos, de ${formatearValor(valores[0], suffix)} a ${formatearValor(valores[valores.length - 1], suffix)}`}
      style={{ display: 'block', overflow: 'visible' }}
    >
      <title>
        {fechas[0]} → {fechas[fechas.length - 1]}
      </title>
      {/* Traza de contexto en el gris de de-énfasis. */}
      <path d={d} fill="none" stroke="rgba(255,255,255,0.28)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      {/* El período actual es lo que el lector debe encontrar primero. */}
      <circle cx={ultimo.x} cy={ultimo.y} r={4} fill="var(--primary)" stroke="var(--card-bg, #121826)" strokeWidth={2}>
        <title>{`${ultimo.fecha}: ${formatearValor(ultimo.v, suffix)}`}</title>
      </circle>
      {/* Cada vértice acepta puntero para consultar su fecha y valor. */}
      {puntos.slice(0, -1).map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={6} fill="transparent">
          <title>{`${p.fecha}: ${formatearValor(p.v, suffix)}`}</title>
        </circle>
      ))}
    </svg>
  );
}

export function TrendPanel({ history, loading }: { history: HistorySeries | null; loading: boolean }) {
  if (loading) {
    return (
      <div className="dashboard-card glass">
        <div className="card-header">
          <span className="card-title">📈 Evolución de la gobernanza</span>
        </div>
        <div style={{ padding: '16px 4px', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
          Consultando el histórico…
        </div>
      </div>
    );
  }

  if (!history || !history.available) {
    const registrados = history?.pointCount ?? 0;
    return (
      <div className="dashboard-card glass">
        <div className="card-header">
          <span className="card-title">📈 Evolución de la gobernanza</span>
          <span className="badge badge-info">Acumulando</span>
        </div>
        <div style={{ padding: '14px 4px', fontSize: '0.82rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          Todavía no hay suficiente histórico para dibujar una tendencia
          {registrados > 0 ? ` (${registrados} día${registrados === 1 ? '' : 's'} registrado${registrados === 1 ? '' : 's'})` : ''}.
          La serie se construye desde hoy: se guarda un punto por día cada vez que se
          consulta el inventario, así que mañana ya podrás comparar.
        </div>
      </div>
    );
  }

  const puntos = history.points;
  const ultimo = puntos[puntos.length - 1];
  const periodo = `${history.firstDate} → ${history.lastDate}`;

  return (
    <div className="dashboard-card glass">
      <div className="card-header">
        <span className="card-title">📈 Evolución de la gobernanza</span>
        <span className="badge badge-info">
          {history.pointCount} día{history.pointCount === 1 ? '' : 's'} · {periodo}
        </span>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
          gap: '14px',
          marginTop: '14px',
        }}
      >
        {METRICAS.map(({ field, label, polarity, suffix }) => {
          const valores = puntos
            .map((p) => p[field] as number | undefined)
            .filter((v): v is number => typeof v === 'number');
          const fechas = puntos.filter((p) => typeof p[field] === 'number').map((p) => p.date);
          const delta = history.deltas[field as string];
          const tieneDelta = typeof delta === 'number' && delta !== 0;
          const flecha = tieneDelta ? (delta > 0 ? '↑' : '↓') : '→';

          return (
            <div
              key={field as string}
              style={{
                background: 'rgba(255,255,255,0.025)',
                border: '1px solid rgba(255,255,255,0.06)',
                borderRadius: '10px',
                padding: '14px',
              }}
            >
              <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginBottom: '6px' }}>
                {label}
              </div>
              <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: '10px' }}>
                <div>
                  <div style={{ fontSize: '1.5rem', fontWeight: 600, color: '#fff', lineHeight: 1.1 }}>
                    {formatearValor(ultimo[field] as number | undefined, suffix)}
                  </div>
                  <div
                    style={{
                      fontSize: '0.75rem',
                      marginTop: '4px',
                      color: colorDelta(delta ?? 0, polarity),
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                    }}
                  >
                    <span aria-hidden="true">{flecha}</span>
                    <span>
                      {tieneDelta
                        ? `${delta > 0 ? '+' : ''}${formatearValor(Math.abs(delta) * (delta < 0 ? -1 : 1), suffix)}`
                        : 'sin cambio'}
                    </span>
                    <span style={{ color: 'var(--text-secondary)', opacity: 0.8 }}>en el período</span>
                  </div>
                </div>
                <Sparkline valores={valores} fechas={fechas} suffix={suffix} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

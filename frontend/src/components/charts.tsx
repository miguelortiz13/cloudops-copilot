import { useEffect, useMemo, useRef, useState } from 'react';
import { longDate, money, moneyAxis, shortDate } from '../lib/format';
import type { CostGroup } from '../lib/types';

/** Ticks limpios (1, 2, 2.5, 5 × 10^n) que cubren [0, max]. */
function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0];
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const ticks: number[] = [];
  for (let v = 0; v <= max + step * 0.001; v += step) ticks.push(Number(v.toFixed(10)));
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const obs = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    obs.observe(ref.current);
    return () => obs.disconnect();
  }, []);
  return [ref, width];
}

/** Columna con extremo de datos redondeado (4px) y base cuadrada. */
function columnPath(x: number, y: number, w: number, h: number): string {
  if (h <= 0) return '';
  const r = Math.min(4, w / 2, h);
  return `M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h} Z`;
}

/**
 * Gasto diario en columnas.
 *
 * Forma de énfasis: los últimos `highlightLast` días van en el color de acento
 * y el periodo anterior en gris, como contexto. Es una sola serie (gasto por
 * día), así que no lleva cuadro de leyenda: la distinción de periodos se nombra
 * en la leyenda mínima de abajo.
 */
export function DailyCostChart({ data, currency, highlightLast = 30, height = 220 }: {
  data: { date: string; cost: number }[];
  currency: string;
  highlightLast?: number;
  height?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const margin = { top: 12, right: 8, bottom: 26, left: 56 };
  const plotW = Math.max(0, width - margin.left - margin.right);
  const plotH = height - margin.top - margin.bottom;

  const max = Math.max(0, ...data.map((d) => d.cost));
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1] || 1;
  const slot = data.length ? plotW / data.length : 0;
  const barW = Math.max(1, Math.min(24, slot - 2));
  const cutoff = data.length - highlightLast;

  // Etiquetas del eje X: una por semana, empezando por el último día.
  const xLabels = useMemo(() => {
    const idx: number[] = [];
    for (let i = data.length - 1; i >= 0; i -= 7) idx.push(i);
    return idx;
  }, [data.length]);

  const h = hover !== null ? data[hover] : null;

  return (
    <div className="chart" ref={ref} onMouseLeave={() => setHover(null)}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label="Gasto diario">
          <g className="chart-grid">
            {ticks.map((t) => {
              const y = margin.top + plotH - (t / top) * plotH;
              return <line key={t} x1={margin.left} x2={width - margin.right} y1={y} y2={y} />;
            })}
          </g>
          <g className="chart-axis">
            {ticks.map((t) => {
              const y = margin.top + plotH - (t / top) * plotH;
              return (
                <text key={t} x={margin.left - 8} y={y + 4} textAnchor="end">
                  {moneyAxis(t, currency)}
                </text>
              );
            })}
            {xLabels.map((i) => (
              <text key={i} x={margin.left + i * slot + slot / 2} y={height - 6} textAnchor="middle">
                {shortDate(data[i].date)}
              </text>
            ))}
          </g>
          {data.map((d, i) => {
            const bh = (d.cost / top) * plotH;
            const x = margin.left + i * slot + (slot - barW) / 2;
            const y = margin.top + plotH - bh;
            const current = i >= cutoff;
            return (
              <g key={d.date}>
                <path
                  d={columnPath(x, y, barW, bh)}
                  fill={current ? 'var(--series-1)' : 'var(--series-muted)'}
                  opacity={hover === null || hover === i ? 1 : 0.55}
                />
                {/* Zona de interacción: la columna completa, no solo la barra. */}
                <rect
                  x={margin.left + i * slot}
                  y={margin.top}
                  width={slot}
                  height={plotH}
                  fill="transparent"
                  onMouseEnter={() => setHover(i)}
                  tabIndex={-1}
                />
              </g>
            );
          })}
          <line
            className="chart-baseline"
            x1={margin.left}
            x2={width - margin.right}
            y1={margin.top + plotH}
            y2={margin.top + plotH}
          />
        </svg>
      )}
      {h && hover !== null && (
        <div
          className="chart-tooltip"
          style={{
            left: Math.min(Math.max(margin.left + hover * slot + slot / 2, 90), width - 90),
            top: margin.top + plotH - (h.cost / top) * plotH,
          }}
        >
          <div className="tt-value">{money(h.cost, currency)}</div>
          <div className="tt-row">
            <span className="tt-key" style={{ background: hover >= cutoff ? 'var(--series-1)' : 'var(--series-muted)' }} />
            {longDate(h.date)}
          </div>
        </div>
      )}
      <div className="legend" style={{ marginTop: 8 }}>
        <span className="legend-item">
          <span className="legend-swatch" style={{ background: 'var(--series-1)' }} />
          Últimos {highlightLast} días
        </span>
        <span className="legend-item">
          <span className="legend-swatch" style={{ background: 'var(--series-muted)' }} />
          {highlightLast} días anteriores
        </span>
      </div>
    </div>
  );
}

/** Tabla equivalente del gráfico diario (accesibilidad y lectura exacta). */
export function DailyCostTable({ data, currency }: { data: { date: string; cost: number }[]; currency: string }) {
  return (
    <div className="table-wrap" style={{ maxHeight: 280, overflowY: 'auto' }}>
      <table className="table">
        <thead><tr><th>Día</th><th className="num">Gasto</th></tr></thead>
        <tbody>
          {[...data].reverse().map((d) => (
            <tr key={d.date}><td>{longDate(d.date)}</td><td className="num">{money(d.cost, currency)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Lista de barras horizontales para desgloses de magnitud.
 *
 * Una sola serie, un solo color (slot 1): el largo ya codifica el valor, así
 * que no se repite con una rampa de color. La etiqueta "Otros" y las claves
 * "Sin <tag>" van en gris porque no son una categoría real.
 */
export function BarList({ items, currency, onSelect, emptyText = 'Sin datos' }: {
  items: CostGroup[];
  currency: string;
  onSelect?: (key: string) => void;
  emptyText?: string;
}) {
  if (!items.length) return <div className="empty">{emptyText}</div>;
  const max = Math.max(...items.map((i) => i.cost), 0.0001);
  return (
    <div className="barlist">
      {items.map((it) => {
        const muted = it.key === 'Otros' || it.key.startsWith('Sin ') || it.key === '—';
        return (
          <div
            key={it.key}
            className="barlist-row"
            title={`${it.key}: ${money(it.cost, currency)} (${it.share} %)`}
            onClick={onSelect ? () => onSelect(it.key) : undefined}
            style={onSelect ? { cursor: 'pointer' } : undefined}
          >
            <span className={`barlist-label truncate ${muted ? 'muted' : ''}`}>{it.key}</span>
            <span className="barlist-track">
              <span className={`barlist-bar ${muted ? 'is-muted' : ''}`} style={{ width: `${(it.cost / max) * 100}%` }} />
            </span>
            <span className="barlist-value">
              {money(it.cost, currency)}
              <small>{it.share.toLocaleString('es-CO', { maximumFractionDigits: 1 })} %</small>
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** Sparkline de una serie: traza en gris y el último punto en el acento. */
export function Sparkline({ values, width = 120, height = 32 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) return null;
  const pad = 4;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => [
    pad + (i / (values.length - 1)) * (width - pad * 2),
    pad + (1 - (v - min) / span) * (height - pad * 2),
  ]);
  const [lx, ly] = pts[pts.length - 1];
  return (
    <svg width={width} height={height} aria-hidden="true" style={{ overflow: 'visible' }}>
      <polyline
        points={pts.map((p) => p.join(',')).join(' ')}
        fill="none"
        stroke="var(--series-muted)"
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={lx} cy={ly} r={4} fill="var(--series-1)" stroke="var(--bg-surface)" strokeWidth={2} />
    </svg>
  );
}

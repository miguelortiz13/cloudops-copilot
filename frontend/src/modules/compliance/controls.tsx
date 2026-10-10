import type { ControlRef, ControlStatus } from '../../lib/types';
import { CONTROL_STATUS, SHORT } from './status';

/** Estado de un control y etiquetas de control, compartidos con Seguridad. */
export function ControlStatusBadge({ status }: { status: ControlStatus }) {
  const s = CONTROL_STATUS[status];
  return (
    <span className="badge" title={s.hint}>
      {s.dot ? <span className={`dot ${s.dot}`} aria-hidden="true" /> : <span className="dot" aria-hidden="true" style={{ background: 'var(--border-strong)' }} />}
      {s.label}
    </span>
  );
}

/** Controles que evidencia una regla o un hallazgo: "CIS 6.1", "ISO A.8.20 (parcial)". */
export function ControlRefs({ frameworks }: { frameworks: Record<string, ControlRef[]> }) {
  const refs = Object.entries(frameworks).flatMap(([m, cs]) => cs.map((c) => ({ m, ...c })));
  if (!refs.length) return <span className="muted">—</span>;
  return (
    <span className="row" style={{ gap: 4, flexWrap: 'wrap' }}>
      {refs.map((r) => (
        <span key={`${r.m}-${r.control}`} className="badge mono" title={r.match === 'parcial' ? 'Evidencia parcial' : 'Evidencia directa'}>
          {SHORT[r.m] ?? r.m} {r.control}{r.match === 'parcial' ? '*' : ''}
        </span>
      ))}
    </span>
  );
}

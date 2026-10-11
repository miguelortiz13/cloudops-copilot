import { useEffect, useId, type ReactNode } from 'react';
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Info, Minus, X } from 'lucide-react';
import type { Severity } from '../lib/types';

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1 className="page-title">{title}</h1>
        {description && <p className="page-desc">{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function Section({ title, description, actions, children }: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="section">
      <div className="section-head">
        <div>
          <h2 className="section-title">{title}</h2>
          {description && <p className="section-desc">{description}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function Card({ title, subtitle, actions, children, footer, flush, className, refreshing }: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  flush?: boolean;
  className?: string;
  refreshing?: boolean;
}) {
  return (
    <div className={`card ${refreshing ? 'is-refreshing' : ''} ${className ?? ''}`}>
      {(title || actions) && (
        <div className="card-head">
          <div>
            {title && <div className="card-title">{title}</div>}
            {subtitle && <div className="card-subtitle">{subtitle}</div>}
          </div>
          {actions}
        </div>
      )}
      {children !== undefined && <div className={`card-body ${flush ? 'flush' : ''}`}>{children}</div>}
      {footer && <div className="card-foot">{footer}</div>}
    </div>
  );
}

/** Dirección de una variación y si subir es bueno, malo o neutro. */
export type Polarity = 'up-good' | 'up-bad' | 'neutral';

export function Delta({ value, polarity = 'neutral', suffix = '%', label }: {
  value: number | null | undefined;
  polarity?: Polarity;
  suffix?: string;
  label?: string;
}) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  const up = value > 0;
  const flat = Math.abs(value) < 0.05;
  const good = polarity === 'neutral' || flat ? null : polarity === 'up-good' ? up : !up;
  const cls = good === null ? 'delta-neutral' : good ? 'delta-good' : 'delta-bad';
  const Icon = flat ? Minus : up ? ArrowUpRight : ArrowDownRight;
  const text = `${up ? '+' : ''}${value.toLocaleString('es-CO', { maximumFractionDigits: 1 })}${suffix}`;
  return (
    <span className={`delta ${cls}`}>
      <Icon size={14} aria-hidden="true" />
      {text}
      {label && <span className="muted" style={{ fontWeight: 400 }}>&nbsp;{label}</span>}
    </span>
  );
}

export function StatTile({ label, value, unit, meta, delta, hero, icon, refreshing }: {
  label: ReactNode;
  value: ReactNode;
  unit?: string;
  meta?: ReactNode;
  delta?: ReactNode;
  hero?: boolean;
  icon?: ReactNode;
  refreshing?: boolean;
}) {
  return (
    <div className={`card stat ${hero ? 'stat-hero' : ''} ${refreshing ? 'is-refreshing' : ''}`}>
      <div className="stat-label">{icon}{label}</div>
      <div className="stat-value">
        {value}
        {unit && <small>{unit}</small>}
      </div>
      {(delta || meta) && (
        <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
          {delta}
          {meta && <span className="stat-meta">{meta}</span>}
        </div>
      )}
    </div>
  );
}

export function Badge({ children, tone }: { children: ReactNode; tone?: 'accent' }) {
  return <span className={`badge ${tone === 'accent' ? 'badge-accent' : ''}`}>{children}</span>;
}

const SEVERITY: Record<Severity, { label: string; dot: string }> = {
  critica: { label: 'Crítica', dot: 'dot-critical' },
  alta: { label: 'Alta', dot: 'dot-serious' },
  media: { label: 'Media', dot: 'dot-warning' },
};

/** Severidad: siempre punto de color + texto, nunca solo color. */
export function SeverityBadge({ severity }: { severity: Severity }) {
  const s = SEVERITY[severity] ?? SEVERITY.media;
  return (
    <span className="badge">
      <span className={`dot ${s.dot}`} aria-hidden="true" />
      {s.label}
    </span>
  );
}

export function StatusBadge({ ok, okLabel, badLabel }: { ok: boolean; okLabel: string; badLabel: string }) {
  return (
    <span className="badge">
      <span className={`dot ${ok ? 'dot-good' : 'dot-critical'}`} aria-hidden="true" />
      {ok ? okLabel : badLabel}
    </span>
  );
}

export function Notice({ tone = 'info', children, onClose }: {
  tone?: 'info' | 'warning' | 'critical';
  children: ReactNode;
  onClose?: () => void;
}) {
  const Icon = tone === 'info' ? Info : AlertTriangle;
  return (
    <div className={`notice ${tone !== 'info' ? `notice-${tone}` : ''}`} role={tone === 'info' ? 'status' : 'alert'}>
      <Icon size={16} aria-hidden="true" />
      <div style={{ flex: 1 }}>{children}</div>
      {onClose && (
        <button className="btn btn-ghost btn-sm btn-icon" onClick={onClose} aria-label="Cerrar aviso">
          <X size={14} />
        </button>
      )}
    </div>
  );
}

export function Empty({ title, children }: { title?: string; children?: ReactNode }) {
  return (
    <div className="empty">
      {title && <strong>{title}</strong>}
      {children}
    </div>
  );
}

export function Loading({ label = 'Cargando…' }: { label?: string }) {
  return (
    <div className="empty" aria-busy="true">
      <div className="spinner" />
      {label}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="empty">
      <strong>No se pudo cargar</strong>
      <span>{error}</span>
      {onRetry && <button className="btn btn-sm" onClick={onRetry}>Reintentar</button>}
    </div>
  );
}

export function Meter({ value, tone }: { value: number; tone?: 'good' | 'warning' | 'critical' }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className={`meter ${tone ? `is-${tone}` : ''}`} role="meter" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { id: T; label: string; count?: number }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          className={`tab ${value === t.id ? 'is-active' : ''}`}
          onClick={() => onChange(t.id)}
        >
          {t.label}
          {t.count !== undefined && <span className="tab-count">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Segmented<T extends string>({ options, value, onChange, label }: {
  options: { id: T; label: string }[];
  value: T;
  onChange: (id: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.id}
          role="radio"
          aria-checked={value === o.id}
          className={value === o.id ? 'is-active' : ''}
          onClick={() => onChange(o.id)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function useEscape(onClose: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
}

export function Drawer({ title, subtitle, onClose, children, footer }: {
  title: ReactNode;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useEscape(onClose);
  const titleId = useId();
  return (
    <>
      <div className="overlay" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <div className="drawer-head">
          <div style={{ minWidth: 0 }}>
            <div className="card-title" id={titleId} style={{ fontSize: 16 }}>{title}</div>
            {subtitle && <div className="card-subtitle">{subtitle}</div>}
          </div>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Cerrar"><X size={16} /></button>
        </div>
        <div className="drawer-body">{children}</div>
        {footer && <div className="drawer-foot">{footer}</div>}
      </aside>
    </>
  );
}

export function Modal({ title, subtitle, onClose, children, footer }: {
  title: ReactNode;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useEscape(onClose);
  const titleId = useId();
  return (
    <>
      <div className="overlay" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <div className="drawer-head">
          <div style={{ minWidth: 0 }}>
            <div className="card-title" id={titleId} style={{ fontSize: 16 }}>{title}</div>
            {subtitle && <div className="card-subtitle">{subtitle}</div>}
          </div>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Cerrar"><X size={16} /></button>
        </div>
        <div className="drawer-body">{children}</div>
        {footer && <div className="drawer-foot">{footer}</div>}
      </div>
    </>
  );
}

export function Pagination({ page, pageSize, total, onPage }: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  return (
    <div className="pagination">
      <span>{from.toLocaleString('es-CO')}–{to.toLocaleString('es-CO')} de {total.toLocaleString('es-CO')}</span>
      <div className="row">
        <button className="btn btn-sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>Anterior</button>
        <span>Página {page} de {pages}</span>
        <button className="btn btn-sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>Siguiente</button>
      </div>
    </div>
  );
}

import { Fragment, useState } from 'react';
import { get, post } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, day, number, shortType } from '../../lib/format';
import type { FindingEvent, FindingStatus, ManagedFinding, ManagedFindings } from '../../lib/types';
import { useApp } from '../../state/hooks';
import {
  Card, Drawer, Empty, ErrorState, Loading, Notice, Section, Segmented, SeverityBadge, StatTile,
} from '../../components/ui';
import { ControlRefs } from '../compliance/controls';

type Filter = 'activos' | 'aceptado' | 'resuelto' | 'todos';

const STATUS: Record<FindingStatus, { label: string; dot?: string }> = {
  abierto: { label: 'Abierto' },
  asumido: { label: 'Asumido' },
  aceptado: { label: 'Riesgo aceptado' },
  resuelto: { label: 'Resuelto', dot: 'dot-good' },
};

const EVENTO: Record<FindingEvent['kind'], string> = {
  detectado: 'Detectado por el recolector',
  estado: 'Cambio de estado',
  resuelto: 'Resuelto: ya no se detecta',
  reabierto: 'Reabierto: se volvió a detectar',
  vencido: 'Venció la aceptación del riesgo',
};

function StatusBadge({ status }: { status: FindingStatus }) {
  const s = STATUS[status];
  return (
    <span className="badge">
      {s.dot && <span className={`dot ${s.dot}`} aria-hidden="true" />}
      {s.label}
    </span>
  );
}

const DETALLE: Record<string, string> = {
  location: 'Región', port: 'Puerto', source: 'Origen', ruleName: 'Regla del NSG',
  asociado: 'NSG asociado a una red', sinFirewall: 'Sin firewall de red',
};

function valor(v: unknown): string {
  if (v === true) return 'Sí';
  if (v === false) return 'No';
  return String(v);
}

function tomorrow(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().slice(0, 10);
}

/**
 * Gestión de hallazgos: el ciclo de vida que guarda la base.
 *
 * El recolector diario detecta, resuelve (cuando el problema desaparece) y
 * reabre. Aquí una persona asume un hallazgo o acepta el riesgo con fecha de
 * vencimiento y justificación. "Resuelto" no se elige a mano: se corrige el
 * recurso y la siguiente recolección lo confirma.
 */
export function ManagementView() {
  const { askAgent } = useApp();
  const { data, error, loading, refreshing, reload } = useApi<ManagedFindings>('managed-findings', () => get('/api/findings'));
  const [filter, setFilter] = useState<Filter>('activos');
  const [selected, setSelected] = useState<ManagedFinding | null>(null);
  // Referencia fija para "vence pronto": no cambia entre renders.
  const [ahora] = useState(() => Date.now());

  if (loading) return <Loading label="Leyendo los hallazgos…" />;
  if (error && !data) {
    return (
      <div className="stack">
        <Notice tone="warning"><strong>La gestión no está disponible.</strong> {error}. Los hallazgos en vivo siguen en la otra pestaña.</Notice>
        <ErrorState error={error} onRetry={reload} />
      </div>
    );
  }
  if (!data) return null;

  const n = (s: FindingStatus) => data.by_status[s] ?? 0;
  const items = data.items.filter((f) =>
    filter === 'todos' ? true : filter === 'activos' ? f.status === 'abierto' || f.status === 'asumido' : f.status === filter);
  const vencenPronto = data.items.filter((f) => f.status === 'aceptado' && f.accepted_until
    && (new Date(f.accepted_until).getTime() - ahora) / 86_400_000 <= 14).length;

  return (
    <div className="stack" style={{ gap: 24 }}>
      <div className="grid grid-4">
        <StatTile refreshing={refreshing} label="Abiertos" value={number(n('abierto'))} meta="Sin responsable todavía" />
        <StatTile refreshing={refreshing} label="Asumidos" value={number(n('asumido'))} meta="Con responsable" />
        <StatTile refreshing={refreshing} label="Riesgo aceptado" value={number(n('aceptado'))}
          meta={vencenPronto ? `${vencenPronto} vence(n) en 14 días o menos` : 'Con fecha de vencimiento'} />
        <StatTile refreshing={refreshing} icon={<span className="dot dot-good" />} label="Resueltos" value={number(n('resuelto'))}
          meta="Confirmados por el recolector" />
      </div>

      <Section
        title="Hallazgos"
        description="Ordenados por severidad. Cada fila es un problema concreto en un recurso; su historial muestra quién hizo qué y cuándo."
        actions={
          <Segmented label="Estado" value={filter} onChange={setFilter} options={[
            { id: 'activos', label: `Activos (${n('abierto') + n('asumido')})` },
            { id: 'aceptado', label: `Aceptados (${n('aceptado')})` },
            { id: 'resuelto', label: `Resueltos (${n('resuelto')})` },
            { id: 'todos', label: 'Todos' },
          ]} />
        }
      >
        <Card flush refreshing={refreshing}>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Severidad</th><th>Hallazgo</th><th>Estado</th><th>Detectado</th><th /></tr>
              </thead>
              <tbody>
                {items.map((f) => (
                  <tr key={f.id}>
                    <td style={{ width: 110 }}><SeverityBadge severity={f.severity} /></td>
                    <td>
                      <span className="primary-cell">{f.title}</span>
                      <span className="sub">{[f.resource_name, f.resource_group, f.account].filter(Boolean).join(' · ')}</span>
                    </td>
                    <td>
                      <StatusBadge status={f.status} />
                      {f.status === 'asumido' && f.owner && <span className="sub">{f.owner}</span>}
                      {f.status === 'aceptado' && f.accepted_until && <span className="sub">hasta el {day(f.accepted_until)}</span>}
                      {f.status === 'resuelto' && f.resolved_at && <span className="sub">el {day(f.resolved_at)}</span>}
                    </td>
                    <td className="secondary">{day(f.first_seen)}</td>
                    <td>
                      <div className="row-actions">
                        <button className="btn btn-sm" onClick={() => setSelected(f)}>
                          {f.status === 'resuelto' ? 'Ver' : 'Gestionar'}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr><td colSpan={5} className="table-empty">No hay hallazgos en este estado.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </Section>

      <div className="muted" style={{ fontSize: 12.5 }}>
        Datos del recolector diario{data.collected_at && <> · última recolección {dateTime(data.collected_at)}</>}
        {' '}· Un hallazgo corregido en Azure aparece como resuelto tras la siguiente recolección.
      </div>

      {selected && (
        <FindingDrawer
          finding={selected}
          onClose={() => setSelected(null)}
          onChanged={(f) => { setSelected(f); reload(); }}
          onAsk={() => askAgent('secops', `Hallazgo "${selected.title}" en ${selected.resource_name} (grupo ${selected.resource_group ?? '—'}). Dame los pasos y comandos de Azure CLI para remediarlo.`)}
        />
      )}
    </div>
  );
}

type Action = 'asumido' | 'aceptado' | 'abierto';

function FindingDrawer({ finding: f, onClose, onChanged, onAsk }: {
  finding: ManagedFinding;
  onClose: () => void;
  onChanged: (f: ManagedFinding) => void;
  onAsk: () => void;
}) {
  const { toast, can } = useApp();
  const puedeGestionar = can('operador');
  const events = useApi<FindingEvent[]>(`finding-events:${f.id}:${f.status}`, () => get(`/api/findings/${f.id}/events`));
  const [action, setAction] = useState<Action | null>(null);
  const [note, setNote] = useState('');
  const [owner, setOwner] = useState(f.owner ?? '');
  const [until, setUntil] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const disponibles: Action[] = !puedeGestionar ? []
    : f.status === 'abierto' ? ['asumido', 'aceptado']
    : f.status === 'asumido' ? ['aceptado', 'abierto']
      : f.status === 'aceptado' ? ['asumido', 'abierto'] : [];
  const etiqueta: Record<Action, string> = { asumido: 'Asumir', aceptado: 'Aceptar el riesgo', abierto: 'Reabrir' };
  const invalido = action === 'aceptado' && (!until || !note.trim());

  async function enviar() {
    if (!action) return;
    setBusy(true);
    setError(null);
    try {
      const r = await post<ManagedFinding>(`/api/findings/${f.id}/status`, {
        status: action,
        note: note.trim() || null,
        owner: action === 'asumido' ? owner : undefined,
        accepted_until: action === 'aceptado' ? until : null,
      });
      toast(`Estado actualizado: ${STATUS[r.status].label}.`);
      setAction(null);
      setNote('');
      onChanged(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const detalles = Object.entries(f.details).filter(([k]) => !['name', 'resourceGroup', 'type'].includes(k));

  return (
    <Drawer
      title={f.title}
      subtitle={<><SeverityBadge severity={f.severity} /> <StatusBadge status={f.status} /></>}
      onClose={onClose}
      footer={action ? (
        <>
          <button className="btn" onClick={() => setAction(null)} disabled={busy}>Cancelar</button>
          <button className="btn btn-primary" onClick={enviar} disabled={busy || invalido}>
            {busy ? 'Guardando…' : etiqueta[action]}
          </button>
        </>
      ) : (
        <>
          <button className="btn btn-ghost" onClick={onAsk}>Preguntar al agente</button>
          {disponibles.map((a) => (
            <button key={a} className={`btn ${a === 'asumido' ? 'btn-primary' : ''}`} onClick={() => setAction(a)}>{etiqueta[a]}</button>
          ))}
        </>
      )}
    >
      <dl className="kv">
        <dt>Recurso</dt><dd className="mono">{f.resource_name}</dd>
        {f.resource_type && <><dt>Tipo</dt><dd>{shortType(f.resource_type)}</dd></>}
        {f.resource_group && <><dt>Grupo</dt><dd>{f.resource_group}</dd></>}
        {f.account && <><dt>Suscripción</dt><dd>{f.account}</dd></>}
        {detalles.map(([k, v]) => <Fragment key={k}><dt>{DETALLE[k] ?? k}</dt><dd>{valor(v)}</dd></Fragment>)}
        <dt>Detectado</dt><dd>{dateTime(f.first_seen)}</dd>
        <dt>Visto por última vez</dt><dd>{dateTime(f.last_seen)}</dd>
        {f.owner && <><dt>Responsable</dt><dd>{f.owner}</dd></>}
        {f.accepted_until && <><dt>Aceptado hasta</dt><dd>{day(f.accepted_until)}</dd></>}
        {f.controls && Object.keys(f.controls).length > 0 && <><dt>Controles</dt><dd><ControlRefs frameworks={f.controls} /></dd></>}
      </dl>

      {f.remediation && (
        <div>
          <div className="subhead">Cómo corregirlo</div>
          <p style={{ margin: '6px 0 0', fontSize: 13 }}>{f.remediation}</p>
        </div>
      )}

      {!puedeGestionar && f.status !== 'resuelto' && (
        <Notice>Gestionar hallazgos requiere el rol Operador. Pídeselo a un administrador de la plataforma.</Notice>
      )}

      {f.status === 'resuelto' && (
        <Notice>Se resolvió solo: la recolección del {f.resolved_at ? day(f.resolved_at) : '—'} ya no lo detectó. Si reaparece, se reabre automáticamente.</Notice>
      )}

      {action && (
        <div className="stack" style={{ gap: 12 }}>
          <div className="subhead">{etiqueta[action]}</div>
          {action === 'asumido' && (
            <label className="field">
              Responsable
              <input className="input" value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="Tu usuario, si lo dejas vacío" />
            </label>
          )}
          {action === 'aceptado' && (
            <label className="field">
              Vence el
              <input className="input" type="date" min={tomorrow()} value={until} onChange={(e) => setUntil(e.target.value)} required />
              <span className="hint">Al vencer, el recolector lo reabre si el problema sigue ahí.</span>
            </label>
          )}
          <label className="field">
            {action === 'aceptado' ? 'Justificación (obligatoria)' : 'Nota (opcional)'}
            <textarea className="input textarea" value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000}
              placeholder={action === 'aceptado' ? 'Por qué se acepta y qué lo mitiga' : ''} />
          </label>
          {error && <Notice tone="critical">{error}</Notice>}
        </div>
      )}

      <div>
        <div className="subhead" style={{ marginBottom: 8 }}>Historial</div>
        {events.loading && <Loading label="Cargando historial…" />}
        {events.error && <ErrorState error={events.error} onRetry={events.reload} />}
        {events.data && events.data.length === 0 && <Empty>Sin eventos.</Empty>}
        {events.data && events.data.length > 0 && (
          <ol className="timeline">
            {events.data.map((e, i) => (
              <li key={i}>
                <div>
                  <strong>{EVENTO[e.kind] ?? e.kind}</strong>
                  {e.kind === 'estado' && e.from && e.to && <> · {STATUS[e.from].label} → {STATUS[e.to].label}</>}
                </div>
                <div className="when">{dateTime(e.at)} · {e.actor}</div>
                {e.note && <div className="secondary" style={{ marginTop: 2 }}>{e.note}</div>}
              </li>
            ))}
          </ol>
        )}
      </div>
    </Drawer>
  );
}

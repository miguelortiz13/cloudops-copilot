import { useState } from 'react';
import type { IncidentAction } from '../../lib/types';
import { dateTime } from '../../lib/format';
import { Card, Empty, Section } from '../../components/ui';

/**
 * Acciones de seguimiento del incidente (fase 7.1, plan 12): salen del post-mortem o se agregan a mano; las abiertas
 * aparecen en *Mis pendientes* de su responsable.
 */
export function AccionesSection({ actions, postmortem, operador, accion }: {
  actions: IncidentAction[];
  postmortem: string | null;
  operador: boolean;
  accion: (ruta: string, body: unknown, ok: string) => Promise<boolean>;
}) {
  const [texto, setTexto] = useState('');
  if (!actions.length && !(postmortem && operador)) return null;
  const abiertas = actions.filter((a) => !a.done_at).length;
  return (
    <Section title="Acciones de seguimiento" description={`${abiertas} abierta(s) de ${actions.length}. Las abiertas aparecen en Mis pendientes de su responsable.`}
      actions={operador && postmortem ? <button className="btn btn-sm" onClick={() => accion('actions', { from_postmortem: true }, 'Acciones creadas desde el post-mortem')}>Crear desde el post-mortem</button> : undefined}>
      <Card>
        <div className="stack" style={{ gap: 8 }}>
          {actions.length === 0 ? <Empty>Sin acciones todavía.</Empty> : actions.map((a) => (
            <label key={a.id} className="check" style={{ alignItems: 'flex-start' }}>
              <input type="checkbox" checked={!!a.done_at} disabled={!operador}
                onChange={() => accion(`actions/${a.id}`, { done: !a.done_at }, a.done_at ? 'Acción reabierta' : 'Acción hecha')} />
              <span>
                <span style={a.done_at ? { textDecoration: 'line-through', color: 'var(--text-muted)' } : undefined}>{a.text}</span>
                <span className="secondary" style={{ fontSize: 12 }}> · {a.owner ?? 'sin responsable'}{a.done_at ? ` · hecha ${dateTime(a.done_at)}` : ''}</span>
              </span>
            </label>
          ))}
          {operador && (
            <form className="row-actions" onSubmit={async (e) => {
              e.preventDefault();
              if (texto.trim() && await accion('actions', { text: texto }, 'Acción agregada')) setTexto('');
            }}>
              <input className="input grow" aria-label="Nueva acción" placeholder="Agregar una acción" value={texto} maxLength={500} onChange={(e) => setTexto(e.target.value)} />
              <button className="btn btn-sm" type="submit" disabled={!texto.trim()}>Agregar</button>
            </form>
          )}
        </div>
      </Card>
    </Section>
  );
}

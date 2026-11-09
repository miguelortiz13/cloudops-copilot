import { useState } from 'react';
import { get, post } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, number } from '../../lib/format';
import { useApp } from '../../state/hooks';
import { Card, Empty, Section } from '../../components/ui';

interface Estado { indexado: boolean; modelo?: string | null; actualizado?: string; fragmentos?: number; con_vector?: number; por_tipo?: Record<string, number> }
interface Resultado { tipo: string; titulo: string; fuente: string; enlace: string | null; texto: string }

const TIPO: Record<string, string> = { runbook: 'Runbooks', guia: 'Guía del panel', control: 'Controles', incidente: 'Incidentes resueltos', excepcion: 'Excepciones' };

/** Base de conocimiento (plan 11, hito IA-4): qué hay indexado, reindexar y probar la búsqueda que usa el agente. */
export function ConocimientoSection() {
  const { toast } = useApp();
  const { data, reload } = useApi<Estado>('ia-conocimiento', () => get('/api/ia/conocimiento'));
  const [q, setQ] = useState('');
  const [res, setRes] = useState<{ modo: string; resultados: Resultado[] } | null>(null);

  const reindexar = async () => {
    try {
      await post('/api/ia/conocimiento/reindexar', {});
      toast('Reindexando: solo se generan vectores de lo que cambió');
      setTimeout(reload, 4000);
    } catch (e) {
      toast(`No se pudo reindexar: ${e instanceof Error ? e.message : String(e)}`);
    }
  };
  const buscar = async () => setRes(await get(`/api/ia/conocimiento/buscar?q=${encodeURIComponent(q.trim())}`));

  return (
    <Section title="Base de conocimiento" description="Runbooks, guía del panel, catálogo de controles, incidentes resueltos con diagnóstico correcto y excepciones aprobadas. El agente la consulta con buscar_conocimiento (búsqueda híbrida: palabras y vectores) y cita la fuente; se reindexa cada día."
      actions={<button className="btn btn-sm" onClick={reindexar}>Reindexar</button>}>
      <Card>
        <div className="stack" style={{ gap: 12 }}>
          {!data?.indexado ? <span className="secondary">Todavía sin índice: la búsqueda funciona solo por palabras hasta la primera indexación.</span> : (
            <span className="secondary" style={{ fontSize: 13 }}>
              {number(data.fragmentos ?? 0)} fragmentos ({Object.entries(data.por_tipo ?? {}).map(([t, n]) => `${TIPO[t] ?? t}: ${number(n)}`).join(' · ')}),
              {' '}{number(data.con_vector ?? 0)} con vector{data.modelo ? ` (${data.modelo})` : ''}. Actualizado {data.actualizado ? dateTime(data.actualizado) : '—'}.
            </span>
          )}
          <form className="row-actions" onSubmit={(e) => { e.preventDefault(); if (q.trim().length >= 2) void buscar(); }}>
            <input className="input" style={{ flex: 1 }} aria-label="Probar la búsqueda" placeholder="Probar: el pod se reinicia y el log dice connection refused" value={q} maxLength={300} onChange={(e) => setQ(e.target.value)} />
            <button className="btn btn-sm" type="submit" disabled={q.trim().length < 2}>Buscar</button>
          </form>
          {res && (res.resultados.length === 0 ? <Empty>Sin resultados.</Empty> : (
            <ol className="stack" style={{ gap: 8, margin: 0, paddingLeft: 18, fontSize: 13 }}>
              {res.resultados.map((r) => (
                <li key={r.fuente}>
                  {r.enlace ? <a href={r.enlace}><strong>{r.titulo}</strong></a> : <strong>{r.titulo}</strong>}
                  <span className="secondary"> · {TIPO[r.tipo] ?? r.tipo} · <span className="mono" style={{ fontSize: 11 }}>{r.fuente}</span></span>
                  <div className="secondary">{r.texto.slice(0, 220)}{r.texto.length > 220 ? '…' : ''}</div>
                </li>
              ))}
            </ol>
          ))}
          {res && <span className="hint">Búsqueda {res.modo}.</span>}
        </div>
      </Card>
    </Section>
  );
}

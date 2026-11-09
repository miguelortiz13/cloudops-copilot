import { useState } from 'react';
import { get, post } from '../../lib/api';
import { Markdown } from '../../lib/markdown';
import { useApi } from '../../lib/useApi';
import { dateTime, number } from '../../lib/format';
import { Card, Empty, Loading, Notice } from '../../components/ui';

interface Pendiente { type: string; title: string; why: string; urgency: number; link: string; when: string | null }
interface Cambios {
  configured: boolean; since: string;
  incidents: { new: number; resolved: number; latest: { id: number; title: string; severity: string; status: string }[] };
  findings: { new: number; new_critical: number; resolved: number };
  resources: { new: number; new_outside_iac: number; deleted: number };
  cost_alerts: { new: number };
}

const TONO = ['dot-accent', 'dot-warning', 'dot-serious', 'dot-critical'];
const TIPO: Record<string, string> = { incidente: 'Incidente', hallazgo: 'Hallazgo', costo: 'Costo', excepcion: 'Excepción', silencio: 'Silencio' };
const CLAVE = 'cloudops.ultimaVisita';
const pl = (n: number, uno: string, varios: string) => `${number(n)} ${n === 1 ? uno : varios}`;

let visita: string | null | undefined;

/** La última visita al Resumen: se lee una vez por carga y se reemplaza por ahora (conveniencia por navegador). */
function ultimaVisita(): string | null {
  if (visita !== undefined) return visita;  // StrictMode llama dos veces al inicializador
  try {
    visita = localStorage.getItem(CLAVE);
    localStorage.setItem(CLAVE, new Date().toISOString());
  } catch {
    visita = null;
  }
  return visita;
}

/** Inicio (fase 5 del plan 10): lo que me espera, por urgencia y con el porqué. */
export function MisPendientes() {
  const { data, loading } = useApi<{ configured: boolean; items: Pendiente[] }>('inicio-pendientes', () => get('/api/inicio/pendientes'));
  const [todos, setTodos] = useState(false);
  const [ia, setIa] = useState<{ text?: string; error?: string; cargando?: boolean } | null>(null);
  const items = data?.items ?? [];
  const priorizar = async () => {
    setIa({ cargando: true });
    try {
      setIa({ text: (await post<{ text: string }>('/api/inicio/pendientes/priorizar', {})).text });
    } catch (e) {
      setIa({ error: e instanceof Error ? e.message : String(e) });
    }
  };
  const visibles = todos ? items : items.slice(0, 6);
  return (
    <Card title="Mis pendientes" subtitle="Lo asignado a ti, lo crítico sin responsable y lo que vence pronto" flush
      actions={items.length ? (
        <div className="row-actions">
          <button className="btn btn-sm" disabled={ia?.cargando} onClick={priorizar}>{ia?.cargando ? 'Pensando…' : 'Por dónde empiezo'}</button>
          {items.length > 6 && <button className="btn btn-ghost btn-sm" onClick={() => setTodos(!todos)}>{todos ? 'Ver menos' : `Ver los ${items.length}`}</button>}
        </div>
      ) : undefined}>
      {ia?.text && <div className="msg-body" style={{ padding: '4px 20px 12px' }}><Markdown text={ia.text} /></div>}
      {ia?.error && <div style={{ padding: '4px 20px 12px' }}><Notice tone="critical">{ia.error}</Notice></div>}
      {loading && !data ? <Loading /> : !data?.configured ? <Empty>Sin base de datos no hay pendientes.</Empty> : items.length === 0 ? <Empty title="Nada pendiente">No tienes nada asignado ni por vencer.</Empty> : (
        <div className="table-wrap">
          <table className="table">
            <tbody>
              {visibles.map((p, n) => (
                <tr key={`${p.link}-${n}`}>
                  <td style={{ width: 110 }}><span className="badge"><span className={`dot ${TONO[p.urgency] ?? 'dot-accent'}`} aria-hidden="true" />{TIPO[p.type] ?? p.type}</span></td>
                  <td><a className="primary-cell" href={p.link}>{p.title}</a><span className="sub">{p.why}</span></td>
                  <td className="secondary" style={{ whiteSpace: 'nowrap' }}>{p.when ? dateTime(p.when) : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/** Qué cambió desde la última visita (o en las últimas 24 horas). */
export function QueCambio() {
  const [desde] = useState(ultimaVisita);
  const q = desde ? `?desde=${encodeURIComponent(desde)}` : '';
  const { data, loading } = useApi<Cambios>(`inicio-cambios${q}`, () => get(`/api/inicio/cambios${q}`));
  const lineas = data?.configured ? [
    { hay: data.incidents.new + data.incidents.resolved, enlace: '#/operacion/incidentes',
      texto: [data.incidents.new && pl(data.incidents.new, 'incidente nuevo', 'incidentes nuevos'), data.incidents.resolved && pl(data.incidents.resolved, 'resuelto', 'resueltos')] },
    { hay: data.findings.new + data.findings.resolved, enlace: '#/riesgo/hallazgos',
      texto: [data.findings.new && `${pl(data.findings.new, 'hallazgo nuevo', 'hallazgos nuevos')}${data.findings.new_critical ? ` (${pl(data.findings.new_critical, 'crítico', 'críticos')})` : ''}`,
        data.findings.resolved && pl(data.findings.resolved, 'hallazgo resuelto', 'hallazgos resueltos')] },
    { hay: data.resources.new + data.resources.deleted, enlace: '#/activos/recursos',
      texto: [data.resources.new && `${pl(data.resources.new, 'recurso nuevo', 'recursos nuevos')}${data.resources.new_outside_iac ? `, ${number(data.resources.new_outside_iac)} fuera de Terraform` : ''}`,
        data.resources.deleted && pl(data.resources.deleted, 'recurso borrado', 'recursos borrados')] },
    { hay: data.cost_alerts.new, enlace: '#/costos/alertas', texto: [pl(data.cost_alerts.new, 'alerta de costo nueva', 'alertas de costo nuevas')] },
  ].filter((l) => l.hay > 0) : [];
  return (
    <Card title="Qué cambió" subtitle={data?.since ? `Desde ${desde ? 'tu última visita' : 'hace 24 horas'} (${dateTime(data.since)})` : undefined}>
      {loading && !data ? <Loading /> : !data?.configured ? <Empty>Sin base de datos no hay historial de cambios.</Empty> : lineas.length === 0 ? <Empty>Sin cambios desde entonces.</Empty> : (
        <ul className="stack" style={{ gap: 8, margin: 0, paddingLeft: 18, fontSize: 13 }}>
          {lineas.map((l) => <li key={l.enlace}><a href={l.enlace}>{l.texto.filter(Boolean).join(' · ')}</a></li>)}
          {data.incidents.latest.slice(0, 3).map((i) => (
            <li key={i.id} className="secondary"><a href={`#/operacion/incidentes/${i.id}`}>#{i.id} {i.title}</a> · {i.severity} · {i.status.replace('_', ' ')}</li>
          ))}
        </ul>
      )}
    </Card>
  );
}

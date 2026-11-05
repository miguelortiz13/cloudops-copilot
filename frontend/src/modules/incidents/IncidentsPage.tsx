import { useState } from 'react';
import { get, post } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, number, percent } from '../../lib/format';
import { Markdown } from '../../lib/markdown';
import type { CloseReason, IncidentDetail, IncidentStats, IncidentStatus, IncidentSummary, Severity } from '../../lib/types';
import { useApp } from '../../state/hooks';
import { Card, Empty, ErrorState, Loading, Notice, PageHeader, Section, Segmented, SeverityBadge, StatTile, Tabs } from '../../components/ui';
import { IncidentSettingsView } from './IncidentSettingsView';
import { SilenceForm, SilencesView } from './SilencesView';

const DIAGNOSTICO: Record<IncidentSummary['diagnosis_status'], string> = {
  diagnosticando: 'Diagnosticando…', listo: 'Diagnosticado', sin_modelo: 'Sin modelo', error: 'Falló el modelo',
  limite: 'Tope de diagnósticos', omitido: 'No se diagnostica (ajustes)', agrupado: 'En una tormenta',
};
const ESTADO: Record<IncidentStatus, { label: string; dot: string }> = {
  abierto: { label: 'Abierto', dot: 'dot-critical' }, reconocido: { label: 'Reconocido', dot: 'dot-warning' },
  en_curso: { label: 'En curso', dot: 'dot-warning' }, resuelto: { label: 'Resuelto', dot: 'dot-good' },
  cerrado: { label: 'Cerrado', dot: 'dot-good' },
};
const MOTIVO: Record<CloseReason, string> = {
  solucionado: 'Solucionado', falso_positivo: 'Falso positivo', ruido: 'Ruido', duplicado: 'Duplicado',
};
const EVENTO: Record<string, string> = {
  abierto: 'Abierto', alerta: 'Alerta', diagnostico: 'Diagnóstico', estado: 'Estado', asignado: 'Responsable',
  nota: 'Nota', resuelto: 'Resuelto por la fuente', tormenta: 'Tormenta', postmortem: 'Post-mortem',
};
const VIVOS: IncidentStatus[] = ['abierto', 'reconocido', 'en_curso'];

function duracion(i: IncidentSummary): string {
  const fin = i.resolved_at ? new Date(i.resolved_at) : new Date();
  const min = Math.max(0, Math.round((fin.getTime() - new Date(i.opened_at).getTime()) / 60000));
  return min < 60 ? `${min} min` : `${number(min / 60, 1)} h`;
}

function Estado({ i }: { i: IncidentSummary }) {
  const e = ESTADO[i.status];
  const extra = i.status === 'cerrado' && i.closed_reason ? ` · ${MOTIVO[i.closed_reason]}` : '';
  return (
    <span className="badge"><span className={`dot ${e.dot}`} aria-hidden="true" />
      {VIVOS.includes(i.status) ? `${e.label} hace ${duracion(i)}` : `${e.label} en ${duracion(i)}${extra}`}</span>
  );
}

type Vista = 'incidentes' | 'silencios' | 'ajustes';
type Filtro = 'vivos' | 'todos' | 'terminados';

/**
 * Incidentes: alertas agrupadas y diagnosticadas por el agente de IA (plan 09,
 * etapa B), con su gestión: estado, responsable, notas, línea de tiempo,
 * post-mortem, silencios y ajustes.
 */
export function IncidentsPage({ incidente, onIncidente }: { incidente?: string; onIncidente: (id: number) => void }) {
  const [vista, setVista] = useState<Vista>('incidentes');
  return (
    <>
      <PageHeader
        title="Incidentes"
        description="Alertas agrupadas en incidentes y diagnosticadas por el agente de IA con herramientas de solo lectura. Gestiona su estado, silencia el ruido y ajusta qué se diagnostica y qué se avisa."
      />
      <Tabs value={vista} onChange={setVista} tabs={[{ id: 'incidentes', label: 'Incidentes' }, { id: 'silencios', label: 'Silencios' }, { id: 'ajustes', label: 'Ajustes' }]} />
      <div style={{ marginTop: 16 }}>
        {vista === 'incidentes' && <Lista incidente={incidente} onIncidente={onIncidente} />}
        {vista === 'silencios' && <SilencesView />}
        {vista === 'ajustes' && <IncidentSettingsView />}
      </div>
    </>
  );
}

function Metricas() {
  const { data } = useApi<IncidentStats>('incident-stats', () => get('/api/incidents/stats'));
  if (!data?.configured) return null;
  const precision = data.accuracy === null ? '—' : percent(data.accuracy * 100, 0);
  return (
    <div className="grid grid-4">
      <StatTile label="Abiertos" value={number(data.open)} meta={`${number(data.total)} en ${data.days} días`} />
      <StatTile label="Precisión del diagnóstico" value={precision}
        meta={data.marked ? `${data.correct} de ${data.marked} marcados · objetivo ${percent(data.target * 100, 0)}` : 'Marca los diagnósticos para medirla'} />
      <StatTile label="Mediana para resolver" value={data.median_minutes_to_resolve === null ? '—' : `${number(data.median_minutes_to_resolve)} min`} />
      <StatTile label="Ruido y falsos positivos" value={number(data.noise)} meta="Cerrados con ese motivo" />
    </div>
  );
}

function Lista({ incidente, onIncidente }: { incidente?: string; onIncidente: (id: number) => void }) {
  const [filtro, setFiltro] = useState<Filtro>('vivos');
  const [severidad, setSeveridad] = useState<Severity | ''>('');
  const [cluster, setCluster] = useState('');
  const [dias, setDias] = useState(30);
  const q = new URLSearchParams({ dias: String(dias) });
  if (filtro === 'vivos') q.set('estado', 'vivos');
  if (severidad) q.set('severidad', severidad);
  if (cluster) q.set('cluster', cluster);
  const { data, error, loading, refreshing, reload } = useApi<{ configured: boolean; items: IncidentSummary[] }>(
    `incidents?${q}`, () => get(`/api/incidents?${q}`));

  if (loading) return <Loading label="Consultando la base (puede tardar un minuto si estaba pausada)…" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  const todos = data?.items ?? [];
  const items = filtro === 'terminados' ? todos.filter((i) => !VIVOS.includes(i.status)) : todos;
  const clusters = [...new Set(todos.map((i) => i.cluster).filter(Boolean) as string[])].sort();
  const elegido = items.find((i) => String(i.id) === incidente) ?? (incidente ? undefined : items[0]);

  return (
    <div className="stack" style={{ gap: 24 }}>
      <Metricas />
      <div className="toolbar">
        <Segmented label="Estado" value={filtro} onChange={setFiltro} options={[
          { id: 'vivos', label: 'Vivos' }, { id: 'terminados', label: 'Terminados' }, { id: 'todos', label: 'Todos' }]} />
        <select className="select" aria-label="Severidad" value={severidad} onChange={(e) => setSeveridad(e.target.value as Severity | '')}>
          <option value="">Toda severidad</option><option value="critica">Crítica</option><option value="alta">Alta</option><option value="media">Media</option>
        </select>
        <select className="select" aria-label="Clúster" value={cluster} onChange={(e) => setCluster(e.target.value)}>
          <option value="">Todo clúster</option>
          {[...new Set([...clusters, cluster].filter(Boolean))].map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select className="select" aria-label="Periodo" value={dias} onChange={(e) => setDias(Number(e.target.value))}>
          <option value={7}>7 días</option><option value={30}>30 días</option><option value={90}>90 días</option>
        </select>
      </div>
      {items.length === 0 ? (
        <Card>
          {todos.length === 0 && filtro !== 'vivos' && !severidad && !cluster ? (
            <Empty title="Todavía no hay incidentes">
              Conecta una fuente: agrega a Alertmanager un <code>webhook_configs</code> hacia{' '}
              <code>/api/alerts/alertmanager?cluster=&lt;nombre&gt;</code> con el token de{' '}
              <code>terraform output alerts_ingest_token</code>. La guía está en <code>docs/labs/incidentes.md</code>.
            </Empty>
          ) : <Empty>Ningún incidente con estos filtros.</Empty>}
        </Card>
      ) : (
        <Card flush refreshing={refreshing}>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>#</th><th>Severidad</th><th>Incidente</th><th>Clúster</th><th>Estado</th><th>Responsable</th><th>Diagnóstico</th><th>Abierto</th></tr></thead>
              <tbody>
                {items.map((i) => (
                  <tr key={i.id} aria-selected={i.id === elegido?.id} style={i.id === elegido?.id ? { background: 'var(--bg-selected)' } : undefined}>
                    <td className="num">{i.id}</td>
                    <td><SeverityBadge severity={i.severity} /></td>
                    <td><button className="btn btn-ghost btn-sm" onClick={() => onIncidente(i.id)}>{i.title}</button></td>
                    <td className="secondary" style={{ whiteSpace: 'nowrap' }}>{i.cluster ?? '—'}</td>
                    <td><Estado i={i} /></td>
                    <td className="secondary">{i.assignee ?? '—'}</td>
                    <td className="secondary">{DIAGNOSTICO[i.diagnosis_status]}{i.feedback ? ` · ${i.feedback}` : ''}</td>
                    <td className="secondary" style={{ whiteSpace: 'nowrap' }}>{dateTime(i.opened_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {(elegido || incidente) && <Detalle id={elegido?.id ?? Number(incidente)} onCambio={reload} onIncidente={onIncidente} />}
    </div>
  );
}

function Detalle({ id, onCambio, onIncidente }: { id: number; onCambio: () => void; onIncidente: (id: number) => void }) {
  const { can, toast } = useApp();
  const { data, error, loading, reload } = useApi<IncidentDetail>(`incident-${id}`, () => get(`/api/incidents/${id}`));
  const [enviando, setEnviando] = useState(false);
  const [cerrando, setCerrando] = useState(false);
  const [motivo, setMotivo] = useState<CloseReason>('solucionado');
  const [comentario, setComentario] = useState('');
  const [nota, setNota] = useState('');
  const [responsable, setResponsable] = useState<string | null>(null);
  const [silenciando, setSilenciando] = useState(false);
  if (loading) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  const operador = can('operador');
  const vivo = VIVOS.includes(data.status);

  const accion = async (ruta: string, body: unknown, ok: string) => {
    setEnviando(true);
    try {
      await post(`/api/incidents/${id}/${ruta}`, body);
      toast(ok);
      reload();
      onCambio();
      return true;
    } catch (e) {
      toast(`No se pudo: ${e instanceof Error ? e.message : String(e)}`);
      return false;
    } finally {
      setEnviando(false);
    }
  };
  const estado = (status: IncidentStatus, extra: object = {}) => accion('status', { status, ...extra }, `Incidente ${ESTADO[status].label.toLowerCase()}`);
  const primera = data.alert_list[0];

  return (
    <div className="stack" style={{ gap: 24 }}>
      {operador && (
        <Card title={`Incidente #${data.id}`} subtitle={<><Estado i={data} /> · Responsable: {data.assignee ?? 'nadie'}</>}>
          <div className="stack" style={{ gap: 12 }}>
            <div className="row-actions" style={{ flexWrap: 'wrap' }}>
              {data.status === 'abierto' && <button className="btn btn-sm" disabled={enviando} onClick={() => estado('reconocido')}>Reconocer</button>}
              {(data.status === 'abierto' || data.status === 'reconocido') && <button className="btn btn-sm" disabled={enviando} onClick={() => estado('en_curso')}>En curso</button>}
              {vivo && <button className="btn btn-sm" disabled={enviando} onClick={() => setCerrando(!cerrando)}>Cerrar…</button>}
              {!vivo && <button className="btn btn-sm" disabled={enviando} onClick={() => estado('abierto')}>Reabrir</button>}
              <button className="btn btn-sm" disabled={enviando || data.diagnosis_status === 'diagnosticando'}
                onClick={() => accion('rediagnose', {}, 'Diagnosticando de nuevo con la foto de ahora')}>Volver a diagnosticar</button>
              <button className="btn btn-sm" onClick={() => setSilenciando(!silenciando)}>Silenciar similares…</button>
            </div>
            {cerrando && (
              <div className="grid grid-2" style={{ gap: 12 }}>
                <label className="field">
                  Motivo
                  <select className="select" value={motivo} onChange={(e) => setMotivo(e.target.value as CloseReason)}>
                    {(Object.keys(MOTIVO) as CloseReason[]).map((m) => <option key={m} value={m}>{MOTIVO[m]}</option>)}
                  </select>
                  <span className="hint">Cerrar no silencia: si la alerta sigue disparando, abre otro incidente.</span>
                </label>
                <label className="field">
                  Comentario (opcional)
                  <input className="input" value={comentario} maxLength={1000} onChange={(e) => setComentario(e.target.value)} />
                </label>
                <div className="row-actions">
                  <button className="btn btn-primary btn-sm" disabled={enviando} onClick={async () => {
                    if (await estado('cerrado', { reason: motivo, comment: comentario })) { setCerrando(false); setComentario(''); }
                  }}>Cerrar incidente</button>
                </div>
              </div>
            )}
            {silenciando && (
              <SilenceForm inicial={{ cluster: data.cluster, namespace: primera?.labels.namespace, alertname: primera?.name }}
                onCreado={() => setSilenciando(false)} onCancelar={() => setSilenciando(false)} />
            )}
            <div className="toolbar">
              <input className="input grow" aria-label="Responsable" placeholder="Responsable (correo o nombre)"
                value={responsable ?? data.assignee ?? ''} maxLength={200} onChange={(e) => setResponsable(e.target.value)} />
              <button className="btn btn-sm" disabled={enviando || responsable === null} onClick={async () => {
                if (await accion('assign', { assignee: responsable }, 'Responsable actualizado')) setResponsable(null);
              }}>Asignar</button>
            </div>
          </div>
        </Card>
      )}

      {data.children.length > 0 && (
        <Notice>
          Tormenta: {data.children.length} incidente(s) más del clúster llegaron casi a la vez y se diagnostican aquí, juntos:{' '}
          {data.children.map((h, n) => (
            <span key={h.id}>{n > 0 && ', '}<button className="btn btn-ghost btn-sm" onClick={() => onIncidente(h.id)}>#{h.id}</button></span>
          ))}
        </Notice>
      )}
      {data.parent_id && (
        <Notice>
          Forma parte de la tormenta del <button className="btn btn-ghost btn-sm" onClick={() => onIncidente(data.parent_id!)}>incidente #{data.parent_id}</button>:
          allí está el diagnóstico conjunto.
        </Notice>
      )}

      <div className="grid grid-2">
        <Section title={`Diagnóstico del incidente #${data.id}`}
          description={data.diagnosed_at ? `Hecho el ${dateTime(data.diagnosed_at)} con ${data.tools.length} consulta(s) de solo lectura.` : undefined}>
          <Card footer={operador ? (
            <>
              <span>¿El diagnóstico fue correcto?</span>
              <div className="row-actions">
                <button className="btn btn-sm" disabled={enviando} aria-pressed={data.feedback === 'correcto'}
                  onClick={() => accion('feedback', { value: 'correcto' }, 'Gracias: la marca alimenta la evaluación del agente')}>Correcto</button>
                <button className="btn btn-sm" disabled={enviando} aria-pressed={data.feedback === 'incorrecto'}
                  onClick={() => accion('feedback', { value: 'incorrecto' }, 'Gracias: la marca alimenta la evaluación del agente')}>Incorrecto</button>
              </div>
            </>
          ) : undefined}>
            {data.diagnosis_status === 'diagnosticando' && <Notice>El agente está investigando; vuelve en un minuto.</Notice>}
            {data.diagnosis ? <div className="msg-body"><Markdown text={data.diagnosis} /></div>
              : data.diagnosis_status !== 'diagnosticando' && <Empty>Sin diagnóstico automático ({DIAGNOSTICO[data.diagnosis_status].toLowerCase()}).</Empty>}
            {data.tools.length > 0 && (
              <p className="secondary" style={{ fontSize: 12, marginTop: 12 }}>Consultó: {data.tools.map((t) => t.nombre).join(', ')}</p>
            )}
          </Card>
        </Section>
        <Section title="Línea de tiempo" description="Lo que hizo la fuente, el agente y cada persona.">
          <Card>
            <ol className="timeline">
              {data.events.map((e, n) => (
                <li key={n}>
                  <div><strong>{EVENTO[e.kind] ?? e.kind}</strong></div>
                  <div className="when">{dateTime(e.at)} · {e.actor}</div>
                  <div className="secondary" style={{ marginTop: 2 }}>{e.text}</div>
                </li>
              ))}
            </ol>
            {data.events.length === 0 && <Empty>Sin eventos (incidente anterior a la línea de tiempo).</Empty>}
            {operador && (
              <div className="toolbar" style={{ marginTop: 12 }}>
                <input className="input grow" aria-label="Nota" placeholder="Agregar una nota" value={nota} maxLength={4000} onChange={(e) => setNota(e.target.value)} />
                <button className="btn btn-sm" disabled={enviando || !nota.trim()} onClick={async () => {
                  if (await accion('notes', { text: nota }, 'Nota agregada')) setNota('');
                }}>Agregar</button>
              </div>
            )}
          </Card>
        </Section>
      </div>

      {(data.postmortem || (!vivo && operador)) && (
        <Section title="Post-mortem (borrador)" description="Redactado por el agente con lo guardado: revísalo antes de compartirlo."
          actions={operador && !vivo ? (
            <button className="btn btn-sm" disabled={enviando} onClick={() => accion('postmortem', {}, 'Post-mortem redactado')}>
              {data.postmortem ? 'Rehacer' : 'Redactar'}
            </button>
          ) : undefined}>
          <Card>{data.postmortem ? <div className="msg-body"><Markdown text={data.postmortem} /></div> : <Empty>Todavía sin borrador.</Empty>}</Card>
        </Section>
      )}

      <Section title="Alertas" description={`${data.alert_list.length} alerta(s) de ${data.source}; última: ${dateTime(data.last_alert_at)}`}>
        <Card flush>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Alerta</th><th>Severidad</th><th>Resumen</th></tr></thead>
              <tbody>
                {data.alert_list.map((a, n) => (
                  <tr key={n}>
                    <td><div>{a.name}</div><div className="mono secondary" style={{ fontSize: 12 }}>{a.labels.namespace ?? ''} {a.labels.pod ?? a.labels.deployment ?? ''}</div></td>
                    <td><SeverityBadge severity={a.severity} /></td>
                    <td className="secondary">{a.summary || a.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </Section>
    </div>
  );
}

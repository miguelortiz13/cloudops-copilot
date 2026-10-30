import { useState } from 'react';
import { get, post } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, number } from '../../lib/format';
import { Markdown } from '../../lib/markdown';
import type { IncidentDetail, IncidentSummary } from '../../lib/types';
import { useApp } from '../../state/hooks';
import { Card, Empty, ErrorState, Loading, Notice, PageHeader, Section, SeverityBadge } from '../../components/ui';

const DIAGNOSTICO: Record<IncidentSummary['diagnosis_status'], string> = {
  diagnosticando: 'Diagnosticando…', listo: 'Diagnosticado', sin_modelo: 'Sin modelo', error: 'Falló el modelo',
  limite: 'Tope de diagnósticos',
};

function duracion(i: IncidentSummary): string {
  const fin = i.resolved_at ? new Date(i.resolved_at) : new Date();
  const min = Math.max(0, Math.round((fin.getTime() - new Date(i.opened_at).getTime()) / 60000));
  return min < 60 ? `${min} min` : `${number(min / 60, 1)} h`;
}

/**
 * Incidentes: alertas de Alertmanager agrupadas y diagnosticadas por el agente de
 * IA con herramientas de solo lectura (plan 09, etapa B). El mismo reporte llega
 * al canal de avisos.
 */
export function IncidentsPage({ incidente, onIncidente }: { incidente?: string; onIncidente: (id: number) => void }) {
  const { data, error, loading, refreshing, reload } = useApi<{ configured: boolean; items: IncidentSummary[] }>(
    'incidents', () => get('/api/incidents'));

  if (loading) return <Loading label="Consultando la base (puede tardar un minuto si estaba pausada)…" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  const items = data?.items ?? [];
  const elegido = items.find((i) => String(i.id) === incidente) ?? items[0];

  return (
    <>
      <PageHeader
        title="Incidentes"
        description="Alertas de Alertmanager agrupadas en incidentes y diagnosticadas por el agente de IA con herramientas de solo lectura. El reporte también llega al canal de avisos."
      />
      {items.length === 0 ? (
        <Card>
          <Empty title="Todavía no hay incidentes">
            Conecta una fuente: agrega a Alertmanager un <code>webhook_configs</code> hacia{' '}
            <code>/api/alerts/alertmanager?cluster=&lt;nombre&gt;</code> con el token de{' '}
            <code>terraform output alerts_ingest_token</code>. La guía está en <code>docs/labs/incidentes.md</code>.
          </Empty>
        </Card>
      ) : (
        <div className="stack" style={{ gap: 24 }}>
          <Card flush refreshing={refreshing}>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>#</th><th>Severidad</th><th>Incidente</th><th>Clúster</th><th>Estado</th><th>Diagnóstico</th><th>Abierto</th></tr></thead>
                <tbody>
                  {items.map((i) => (
                    <tr key={i.id} aria-selected={i.id === elegido?.id} style={i.id === elegido?.id ? { background: 'var(--bg-selected)' } : undefined}>
                      <td className="num">{i.id}</td>
                      <td><SeverityBadge severity={i.severity} /></td>
                      <td><button className="btn btn-ghost btn-sm" onClick={() => onIncidente(i.id)}>{i.title}</button></td>
                      <td className="secondary">{i.cluster ?? '—'}</td>
                      <td>
                        <span className="badge"><span className={`dot ${i.status === 'resuelto' ? 'dot-good' : 'dot-critical'}`} aria-hidden="true" />
                          {i.status === 'resuelto' ? `Resuelto en ${duracion(i)}` : `Abierto hace ${duracion(i)}`}</span>
                      </td>
                      <td className="secondary">{DIAGNOSTICO[i.diagnosis_status]}{i.feedback ? ` · ${i.feedback}` : ''}</td>
                      <td className="secondary" style={{ whiteSpace: 'nowrap' }}>{dateTime(i.opened_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          {elegido && <Detalle id={elegido.id} onCambio={reload} />}
        </div>
      )}
    </>
  );
}

function Detalle({ id, onCambio }: { id: number; onCambio: () => void }) {
  const { can, toast } = useApp();
  const { data, error, loading, reload } = useApi<IncidentDetail>(`incident-${id}`, () => get(`/api/incidents/${id}`));
  const [enviando, setEnviando] = useState(false);
  if (loading) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  const opinar = async (value: 'correcto' | 'incorrecto') => {
    setEnviando(true);
    try {
      await post(`/api/incidents/${id}/feedback`, { value });
      toast('Gracias: la marca alimenta la evaluación del agente');
      reload();
      onCambio();
    } catch (e) {
      toast(`No se pudo guardar: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div className="grid grid-2">
      <Section title={`Diagnóstico del incidente #${data.id}`}
        description={data.diagnosed_at ? `Hecho por el agente el ${dateTime(data.diagnosed_at)} con ${data.tools.length} consulta(s) de solo lectura.` : undefined}>
        <Card footer={can('operador') ? (
          <>
            <span>¿El diagnóstico fue correcto?</span>
            <div className="row-actions">
              <button className="btn btn-sm" disabled={enviando} aria-pressed={data.feedback === 'correcto'} onClick={() => opinar('correcto')}>Correcto</button>
              <button className="btn btn-sm" disabled={enviando} aria-pressed={data.feedback === 'incorrecto'} onClick={() => opinar('incorrecto')}>Incorrecto</button>
            </div>
          </>
        ) : undefined}>
          {data.diagnosis_status === 'diagnosticando' && <Notice>El agente está investigando; vuelve en un minuto.</Notice>}
          {data.diagnosis ? <div className="msg-body"><Markdown text={data.diagnosis} /></div>
            : data.diagnosis_status !== 'diagnosticando' && <Empty>Sin diagnóstico automático ({DIAGNOSTICO[data.diagnosis_status].toLowerCase()}).</Empty>}
          {data.tools.length > 0 && (
            <p className="secondary" style={{ fontSize: 12, marginTop: 12 }}>
              Consultó: {data.tools.map((t) => t.nombre).join(', ')}
            </p>
          )}
        </Card>
      </Section>
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

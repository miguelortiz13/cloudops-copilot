import { useState } from 'react';
import { del, get, post } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime } from '../../lib/format';
import type { Silence } from '../../lib/types';
import { useApp } from '../../state/hooks';
import { Card, Empty, ErrorState, Loading, Notice, PageHeader, Section } from '../../components/ui';

const DURACIONES = [{ h: 1, label: '1 hora' }, { h: 4, label: '4 horas' }, { h: 24, label: '1 día' }, { h: 168, label: '7 días' }, { h: 720, label: '30 días' }];

export interface SilenceScope { cluster?: string | null; namespace?: string | null; alertname?: string | null; target?: string | null }

/** Alcance legible de un silencio: lo vacío es "cualquiera". */
function alcance(s: { cluster: string | null; namespace: string | null; alerta: string | null; objeto: string | null }): string {
  return [s.cluster && `clúster ${s.cluster}`, s.namespace && `namespace ${s.namespace}`, s.alerta && `alerta ${s.alerta}`,
    s.objeto && `objeto que contiene "${s.objeto}"`].filter(Boolean).join(' · ');
}

/**
 * Formulario de silencio. `inicial` llega desde un incidente o una incidencia de
 * Kubernetes; los campos vacíos significan "cualquiera", pero al menos uno es obligatorio.
 */
export function SilenceForm({ inicial, onCreado, onCancelar }: { inicial?: SilenceScope; onCreado: (s: Silence) => void; onCancelar?: () => void }) {
  const { toast } = useApp();
  const [f, setF] = useState({ cluster: inicial?.cluster ?? '', namespace: inicial?.namespace ?? '', alertname: inicial?.alertname ?? '',
    target: inicial?.target ?? '', reason: '', hours: 24 });
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const algo = [f.cluster, f.namespace, f.alertname, f.target].some((x) => x.trim());
  const campo = (k: 'cluster' | 'namespace' | 'alertname' | 'target', label: string, hint?: string) => (
    <label className="field">
      {label}
      <input className="input" value={f[k]} maxLength={200} onChange={(e) => setF({ ...f, [k]: e.target.value })} placeholder="Cualquiera" />
      {hint && <span className="hint">{hint}</span>}
    </label>
  );

  const crear = async () => {
    setEnviando(true);
    setError(null);
    try {
      const s = await post<Silence>('/api/silences', {
        hours: f.hours, reason: f.reason, cluster: f.cluster.trim() || null, namespace: f.namespace.trim() || null,
        alertname: f.alertname.trim() || null, target: f.target.trim() || null,
      });
      toast(`Silenciado hasta el ${dateTime(s.hasta)}`);
      onCreado(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="grid grid-2" style={{ gap: 12 }}>
        {campo('cluster', 'Clúster')}
        {campo('namespace', 'Namespace')}
        {campo('alertname', 'Alerta', 'Regla de Alertmanager (PodCrashLooping) o tipo de aviso: resumen_semanal, atencion_diaria, reporte_mensual, kubernetes')}
        {campo('target', 'Objeto', 'Parte del nombre del pod, deployment, servicio o nodo')}
      </div>
      <div className="grid grid-2" style={{ gap: 12 }}>
        <label className="field">
          Durante
          <select className="select" value={f.hours} onChange={(e) => setF({ ...f, hours: Number(e.target.value) })}>
            {DURACIONES.map((d) => <option key={d.h} value={d.h}>{d.label}</option>)}
          </select>
        </label>
        <label className="field">
          Motivo
          <input className="input" value={f.reason} maxLength={300} onChange={(e) => setF({ ...f, reason: e.target.value })} placeholder="Mantenimiento, ruido conocido…" />
        </label>
      </div>
      {!algo && <span className="hint">Indica al menos un campo: no se puede silenciar todo.</span>}
      {error && <Notice tone="critical">{error}</Notice>}
      <div className="row-actions">
        <button className="btn btn-primary btn-sm" disabled={!algo || enviando} onClick={crear}>Silenciar</button>
        {onCancelar && <button className="btn btn-sm" onClick={onCancelar}>Cancelar</button>}
      </div>
    </div>
  );
}

/** Silencios vigentes: lo que coincide no abre incidentes, no se diagnostica ni se avisa (tampoco las incidencias de Kubernetes). */
export function SilencesView() {
  const { can, toast } = useApp();
  const { data, error, loading, reload } = useApi<{ items: Silence[] }>('silences', () => get('/api/silences'));
  const [nuevo, setNuevo] = useState(false);
  if (loading) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  const items = data?.items ?? [];

  const quitar = async (s: Silence) => {
    try {
      await del(`/api/silences/${s.id}`);
      toast('Silencio quitado');
      reload();
    } catch (e) {
      toast(`No se pudo quitar: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div className="stack" style={{ gap: 24 }}>
      <Section title="Silencios vigentes" description="Las alertas y las incidencias de Kubernetes que coinciden no abren incidentes, no se diagnostican y no se avisan. Vencen solos."
        actions={can('operador') && !nuevo ? <button className="btn btn-sm" onClick={() => setNuevo(true)}>Nuevo silencio</button> : undefined}>
        {nuevo && <Card><SilenceForm onCreado={() => { setNuevo(false); reload(); }} onCancelar={() => setNuevo(false)} /></Card>}
        {items.length === 0 ? <Card><Empty>No hay silencios vigentes.</Empty></Card> : (
          <Card flush>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Qué silencia</th><th>Motivo</th><th>Quién</th><th>Hasta</th><th /></tr></thead>
                <tbody>
                  {items.map((s) => (
                    <tr key={s.id}>
                      <td>{alcance(s)}</td>
                      <td className="secondary">{s.motivo || '—'}</td>
                      <td className="secondary">{s.creado_por}</td>
                      <td className="secondary" style={{ whiteSpace: 'nowrap' }}>{dateTime(s.hasta)}</td>
                      <td>{can('operador') && <button className="btn btn-ghost btn-sm" onClick={() => quitar(s)}>Quitar</button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </Section>
    </div>
  );
}

/** Operación → Silencios. */
export function SilencesPage() {
  return (
    <>
      <PageHeader title="Silencios" description="Silencios vigentes por clúster, namespace, alerta u objeto, con su motivo y su vencimiento." />
      <SilencesView />
    </>
  );
}

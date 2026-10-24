import { useState } from 'react';
import { get } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, day, number, plural } from '../../lib/format';
import type { K8sClusterDetail, K8sClusterSummary, K8sIncident, K8sPod, K8sSupport } from '../../lib/types';
import {
  Card, Drawer, Empty, ErrorState, Loading, Notice, PageHeader, Section, SeverityBadge, StatTile,
} from '../../components/ui';

const DISTRIBUCION: Record<string, string> = {
  aks: 'AKS', eks: 'EKS', gke: 'GKE', k3s: 'k3s', rke2: 'RKE2', k0s: 'k0s', kubernetes: 'Kubernetes',
};

const CATEGORIA: Record<K8sIncident['category'], string> = { nodo: 'Nodo', pod: 'Pod', carga: 'Carga', red: 'Red' };

function hace(segundos: number | null | undefined): string {
  if (segundos == null) return 'sin dato';
  if (segundos < 90) return 'hace un momento';
  if (segundos < 3600) return `hace ${Math.round(segundos / 60)} min`;
  if (segundos < 86400) return `hace ${Math.round(segundos / 3600)} h`;
  return `hace ${Math.round(segundos / 86400)} días`;
}

function tonoSalud(score: number): 'good' | 'warning' | 'critical' {
  return score >= 80 ? 'good' : score >= 50 ? 'warning' : 'critical';
}

function memoria(mib: number | null): string {
  return mib == null ? '—' : mib >= 1024 ? `${number(mib / 1024, 1)} GiB` : `${number(mib)} MiB`;
}

/**
 * Clústeres que reportan con el agente de solo lectura (k8s-agent/): AKS, EKS
 * o fuera de la nube. Los datos son la última foto del agente (cada 5 minutos).
 */
export function KubernetesPage({ cluster, onCluster }: { cluster?: string; onCluster: (name: string) => void }) {
  const lista = useApi<{ clusters: K8sClusterSummary[] }>('k8s-clusters', () => get('/api/k8s/clusters'));

  if (lista.loading) return <Loading />;
  if (lista.error && !lista.data) return <ErrorState error={lista.error} onRetry={lista.reload} />;
  const clusters = lista.data?.clusters ?? [];
  const activo = clusters.find((c) => c.name === cluster) ?? clusters.find((c) => c.reporting) ?? clusters[0];

  return (
    <>
      <PageHeader
        title="Kubernetes"
        description="Clústeres que reportan con el agente de solo lectura: AKS, EKS o fuera de la nube. Cada agente envía una foto cada 5 minutos."
      />
      {clusters.length === 0 ? <SinClusteres /> : (
        <div className="stack" style={{ gap: 24 }}>
          <Flota clusters={clusters} activo={activo?.name} onCluster={onCluster} />
          {activo && (activo.reporting ? <Detalle nombre={activo.name} /> : <SinFoto cluster={activo} />)}
        </div>
      )}
    </>
  );
}

function Soporte({ s }: { s?: K8sSupport }) {
  if (!s || s.status === 'sin_dato' || !s.eol) {
    return <span className="badge"><span className="dot" aria-hidden="true" style={{ background: 'var(--border-strong)' }} />Sin dato</span>;
  }
  const { dot, texto } = {
    vigente: { dot: 'dot-good', texto: `Hasta el ${day(s.eol)}` },
    por_vencer: { dot: 'dot-warning', texto: `Vence en ${plural(s.days_left ?? 0, 'día')}` },
    sin_soporte: { dot: 'dot-critical', texto: `Sin soporte desde el ${day(s.eol)}` },
  }[s.status];
  return <span className="badge"><span className={`dot ${dot}`} aria-hidden="true" />{texto}</span>;
}

/** Todos los clústeres con su versión y fin de soporte; elegir uno abre su detalle. */
function Flota({ clusters, activo, onCluster }: { clusters: K8sClusterSummary[]; activo?: string; onCluster: (name: string) => void }) {
  return (
    <Section title="Flota" description="Fin de soporte según el calendario oficial de Kubernetes; AKS y EKS suelen dar soporte por más tiempo.">
      <Card flush>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Clúster</th><th>Versión</th><th>Soporte</th><th className="num">Nodos listos</th><th className="num">Salud</th><th>Última foto</th></tr></thead>
            <tbody>
              {clusters.map((c) => (
                <tr key={c.name} aria-selected={c.name === activo} style={c.name === activo ? { background: 'var(--bg-selected)' } : undefined}>
                  <td>
                    <button className="btn btn-ghost btn-sm" onClick={() => onCluster(c.name)} aria-current={c.name === activo ? 'true' : undefined}>{c.name}</button>
                    {c.reporting && <div className="secondary" style={{ fontSize: 12, paddingLeft: 8 }}>{DISTRIBUCION[c.distribution ?? ''] ?? c.distribution}</div>}
                  </td>
                  <td>
                    <div className="mono" style={{ fontSize: 12 }}>{c.version ?? '—'}</div>
                    {c.support?.latest_patch && <div className="secondary" style={{ fontSize: 12 }}>Parche {c.support.latest_patch} disponible</div>}
                  </td>
                  <td>{c.reporting ? <Soporte s={c.support} /> : '—'}</td>
                  <td className="num">{c.reporting ? `${number(c.nodes_ready)} / ${number(c.nodes)}` : '—'}</td>
                  <td className="num">{c.reporting ? <span className="badge"><span className={`dot dot-${tonoSalud(c.health ?? 0)}`} aria-hidden="true" />{number(c.health)}</span> : '—'}</td>
                  <td className="secondary">{c.reporting ? <>{hace(c.age_seconds)}{c.stale && <> · <strong>sin reportar</strong></>}</> : 'Nunca reportó'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </Section>
  );
}

function SinClusteres() {
  return (
    <Card>
      <Empty title="Todavía no hay clústeres conectados">
        Agrega el clúster a <code>kubernetes_clusters</code> en Terraform, aplica, y despliega el agente con{' '}
        <code>kubectl apply -k k8s-agent/</code> usando la URL de <code>terraform output kubernetes_agent_upload_urls</code>.
        La guía está en <code>docs/modules/kubernetes-sre.md</code>.
      </Empty>
    </Card>
  );
}

function SinFoto({ cluster }: { cluster: K8sClusterSummary }) {
  return (
    <Notice tone={cluster.error ? 'critical' : 'warning'}>
      {cluster.error ?? `El agente de ${cluster.name} todavía no envió ninguna foto. Revisa que esté corriendo: kubectl -n cloudops logs deploy/cloudops-agent`}
    </Notice>
  );
}

function Detalle({ nombre }: { nombre: string }) {
  const [log, setLog] = useState<K8sPod | null>(null);
  const { data, error, loading, refreshing, reload } = useApi<K8sClusterDetail>(`k8s-cluster-${nombre}`, () => get(`/api/k8s/clusters/${encodeURIComponent(nombre)}`));
  if (loading) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  const salud = data.health ?? 0;
  const incid = data.incident_list;
  const degradadas = data.workload_list.filter((w) => w.ready < w.desired);

  return (
    <div className="stack" style={{ gap: 24 }}>
      {data.stale && (
        <Notice tone="warning">
          La última foto es de {dateTime(data.collected_at)} ({hace(data.age_seconds)}): el agente dejó de reportar o el clúster no tiene salida a Internet.
        </Notice>
      )}

      <div className="grid grid-4">
        <StatTile refreshing={refreshing} icon={<span className={`dot dot-${tonoSalud(salud)}`} />} label="Salud" value={number(salud)} unit="/ 100"
          meta={salud >= 80 ? 'Sano' : salud >= 50 ? 'Con incidencias' : 'Requiere atención'} />
        <StatTile refreshing={refreshing} icon={<span className={`dot ${data.nodes_ready === data.nodes ? 'dot-good' : 'dot-critical'}`} />}
          label="Nodos listos" value={number(data.nodes_ready)} unit={`de ${number(data.nodes)}`}
          meta={`${DISTRIBUCION[data.distribution ?? ''] ?? data.distribution} ${data.version ?? ''}`} />
        <StatTile refreshing={refreshing} label="Pods en ejecución" value={number(data.pods_running)} unit={`de ${number(data.pods)}`}
          meta={`${plural(data.namespaces ?? 0, 'namespace')} · ${plural(data.workloads ?? 0, 'carga')}`} />
        <StatTile refreshing={refreshing} icon={incid.length ? <span className="dot dot-critical" /> : undefined}
          label="Incidencias" value={number(incid.length)}
          meta={`Foto ${hace(data.age_seconds)} · agente ${data.agent_version ?? '—'}`} />
      </div>

      <Section title="Incidencias" description="Calculadas de la última foto: nodos sin responder o con presión, pods que no arrancan, cargas degradadas y servicios sin endpoints.">
        <Card flush refreshing={refreshing}>
          {incid.length ? (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Severidad</th><th>Tipo</th><th>Incidencia</th><th>Namespace</th><th>Detalle</th><th>Siguiente paso</th></tr></thead>
                <tbody>
                  {incid.map((i) => (
                    <tr key={`${i.namespace}/${i.resource}/${i.title}`}>
                      <td><SeverityBadge severity={i.severity} /></td>
                      <td className="secondary">{CATEGORIA[i.category]}</td>
                      <td>{i.title}</td>
                      <td className="mono secondary" style={{ fontSize: 12 }}>{i.namespace ?? '—'}</td>
                      <td className="secondary">{i.detail}</td>
                      <td className="mono" style={{ fontSize: 12 }}>{i.recommendation}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty title="Sin incidencias">Todos los nodos están listos y las cargas tienen sus réplicas.</Empty>}
        </Card>
      </Section>

      <div className="grid grid-2">
        <Section title="Nodos">
          <Card flush refreshing={refreshing}>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Nodo</th><th>Estado</th><th>Roles</th><th>Versión</th><th className="num">CPU</th><th className="num">Memoria</th></tr></thead>
                <tbody>
                  {data.node_list.map((n) => (
                    <tr key={n.name}>
                      <td>
                        <div style={{ whiteSpace: 'nowrap' }}>{n.name}</div>
                        <div className="secondary" style={{ fontSize: 12 }} title={n.os ?? undefined}>{n.arch ?? ''}</div>
                      </td>
                      <td>
                        <span className="badge"><span className={`dot ${n.ready ? (n.pressure.length ? 'dot-warning' : 'dot-good') : 'dot-critical'}`} aria-hidden="true" />
                          {n.ready ? (n.pressure.length ? n.pressure.join(', ') : n.unschedulable ? 'Listo, sin programar' : 'Listo') : 'Sin responder'}</span>
                      </td>
                      <td className="secondary">{n.roles.join(', ')}</td>
                      <td className="mono secondary" style={{ fontSize: 12 }}>{n.kubelet ?? '—'}</td>
                      <td className="num">{n.cpu_m == null ? '—' : `${number(n.cpu_m / 1000, n.cpu_m % 1000 ? 1 : 0)}`}</td>
                      <td className="num">{memoria(n.memory_mib)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </Section>

        <Section title="Cargas" description={degradadas.length ? `${plural(degradadas.length, 'carga degradada', 'cargas degradadas')} primero.` : 'Todas con sus réplicas listas.'}>
          <Card flush refreshing={refreshing}>
            <div className="table-wrap" style={{ maxHeight: 420, overflowY: 'auto' }}>
              <table className="table">
                <thead><tr><th>Carga</th><th>Tipo</th><th className="num">Listas</th></tr></thead>
                <tbody>
                  {data.workload_list.map((w) => (
                    <tr key={`${w.kind}/${w.namespace}/${w.name}`}>
                      <td><div>{w.name}</div><div className="mono secondary" style={{ fontSize: 12 }}>{w.namespace}</div></td>
                      <td className="secondary">{w.kind}</td>
                      <td className="num">
                        <span className="badge"><span className={`dot ${w.ready >= w.desired ? 'dot-good' : w.ready === 0 ? 'dot-critical' : 'dot-warning'}`} aria-hidden="true" />
                          {number(w.ready)} / {number(w.desired)}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </Section>
      </div>

      {data.problem_pods.length > 0 && (
        <Section title="Pods con problemas">
          <Card flush refreshing={refreshing}>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Pod</th><th>Motivo</th><th className="num">Listos</th><th className="num">Reinicios</th><th>Nodo</th><th>Dueño</th><th /></tr></thead>
                <tbody>
                  {data.problem_pods.map((p) => (
                    <tr key={`${p.namespace}/${p.name}`}>
                      <td><div className="mono" style={{ fontSize: 12 }}>{p.name}</div><div className="mono secondary" style={{ fontSize: 12 }}>{p.namespace}</div></td>
                      <td>{p.reason ?? p.phase}</td>
                      <td className="num">{p.ready} / {p.containers}</td>
                      <td className="num">{number(p.restarts)}</td>
                      <td className="secondary">{p.node ?? '—'}</td>
                      <td className="secondary">{p.owner_kind ? `${p.owner_kind}/${p.owner}` : '—'}</td>
                      <td>{p.log && <button className="btn btn-sm" onClick={() => setLog(p)}>Ver log</button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </Section>
      )}

      {log?.log && (
        <Drawer title={`Log de ${log.name}`} onClose={() => setLog(null)}
          subtitle={`${log.namespace} · contenedor ${log.log.container} · ${log.log.previous ? 'ejecución anterior (antes del último reinicio)' : 'ejecución actual'} · foto ${hace(data.age_seconds)}`}>
          <pre className="mono" style={{ fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0 }}>
            {log.log.lines.join('\n') || '(sin líneas)'}
          </pre>
          <p className="secondary" style={{ fontSize: 12, marginTop: 12 }}>
            Las credenciales evidentes se enmascaran en el clúster antes de enviar. Log completo:{' '}
            <code>kubectl logs {log.name} -n {log.namespace} -c {log.log.container}{log.log.previous ? ' --previous' : ''}</code>
          </p>
        </Drawer>
      )}

      <Section title="Eventos de advertencia" description="Los más recientes del clúster (tipo Warning).">
        <Card flush refreshing={refreshing}>
          {data.events.length ? (
            <div className="table-wrap" style={{ maxHeight: 420, overflowY: 'auto' }}>
              <table className="table">
                <thead><tr><th>Último</th><th>Objeto</th><th>Motivo</th><th>Mensaje</th><th className="num">Veces</th></tr></thead>
                <tbody>
                  {data.events.map((e, i) => (
                    <tr key={i}>
                      <td className="secondary" style={{ whiteSpace: 'nowrap' }}>{dateTime(e.last)}</td>
                      <td><div>{e.kind}/{e.name}</div><div className="mono secondary" style={{ fontSize: 12 }}>{e.namespace ?? '—'}</div></td>
                      <td>{e.reason}</td>
                      <td className="secondary">{e.message}</td>
                      <td className="num">{number(e.count)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty>Sin eventos de advertencia.</Empty>}
        </Card>
      </Section>
    </div>
  );
}

import { get } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, number, plural } from '../../lib/format';
import type { K8sClusterDetail, K8sClusterSummary, K8sIncident } from '../../lib/types';
import {
  Card, Empty, ErrorState, Loading, Notice, PageHeader, Section, SeverityBadge, StatTile, Tabs,
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
          {clusters.length > 1 && (
            <Tabs value={activo!.name} onChange={onCluster}
              tabs={clusters.map((c) => ({ id: c.name, label: c.name, count: c.reporting ? Object.values(c.incidents ?? {}).reduce((a, b) => a + b, 0) : undefined }))} />
          )}
          {activo && (activo.reporting ? <Detalle nombre={activo.name} /> : <SinFoto cluster={activo} />)}
        </div>
      )}
    </>
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
                <thead><tr><th>Pod</th><th>Motivo</th><th className="num">Listos</th><th className="num">Reinicios</th><th>Nodo</th><th>Dueño</th></tr></thead>
                <tbody>
                  {data.problem_pods.map((p) => (
                    <tr key={`${p.namespace}/${p.name}`}>
                      <td><div className="mono" style={{ fontSize: 12 }}>{p.name}</div><div className="mono secondary" style={{ fontSize: 12 }}>{p.namespace}</div></td>
                      <td>{p.reason ?? p.phase}</td>
                      <td className="num">{p.ready} / {p.containers}</td>
                      <td className="num">{number(p.restarts)}</td>
                      <td className="secondary">{p.node ?? '—'}</td>
                      <td className="secondary">{p.owner_kind ? `${p.owner_kind}/${p.owner}` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </Section>
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

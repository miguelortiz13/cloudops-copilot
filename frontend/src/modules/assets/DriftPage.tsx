import { get } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, number } from '../../lib/format';
import { Card, Empty, ErrorState, Loading, Notice, PageHeader, Section, StatTile } from '../../components/ui';

interface Drift {
  available: boolean; generated_at?: string; states_read?: number; totals: { deleted: number; tags: number };
  deleted: { id: string; name: string; terraform_type: string | null }[];
  tags: { uid: string; name: string; type: string; changes: { tag: string; terraform: string | null; real: string | null }[] }[];
}

/**
 * Activos → Drift de Terraform: lo que Terraform declara y ya no coincide con la nube (Azure). Lo calcula el job
 * diario con los estados que la plataforma ya lee (fase 3 del plan 10).
 */
export function DriftPage({ onRecurso }: { onRecurso: (uid: string) => void }) {
  const { data, error, loading, reload } = useApi<Drift>('activos-drift', () => get('/api/activos/drift'));
  if (loading) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <>
      <PageHeader title="Drift de Terraform"
        description="Diferencias entre lo que declaran los estados de Terraform y lo que hay en Azure: recursos borrados fuera de Terraform y tags cambiadas a mano. Se calcula en cada recolección diaria." />
      {!data.available ? (
        <Card><Empty title="Todavía sin cálculo">Aparece después de la próxima recolección, si hay estados de Terraform configurados (TFSTATE_ACCOUNT).</Empty></Card>
      ) : (
        <div className="stack" style={{ gap: 24 }}>
          <div className="grid grid-4">
            <StatTile label="Borrados fuera de Terraform" value={number(data.totals.deleted)} meta="El estado los gestiona; Azure ya no los tiene" />
            <StatTile label="Tags cambiadas a mano" value={number(data.totals.tags)} meta="Recursos con tags distintas a las del estado" />
            <StatTile label="Estados leídos" value={number(data.states_read ?? 0)} />
            <StatTile label="Calculado" value={data.generated_at ? dateTime(data.generated_at) : '—'} />
          </div>
          <Notice>Solo Azure y recursos de primer nivel: los hijos (subredes, reglas, asignaciones) no están en el inventario. El próximo <code>terraform plan</code> de cada estado los recrearía o revertiría.</Notice>
          <Section title="Borrados fuera de Terraform" description="Recursos que un estado gestiona y que ya no están en una suscripción que la plataforma ve.">
            <Card flush>
              {data.deleted.length ? (
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>Recurso</th><th>Tipo de Terraform</th><th>Id</th></tr></thead>
                    <tbody>
                      {data.deleted.map((d) => (
                        <tr key={d.id}>
                          <td>{d.name}</td>
                          <td className="mono secondary" style={{ fontSize: 12 }}>{d.terraform_type ?? '—'}</td>
                          <td className="mono secondary" style={{ fontSize: 12, wordBreak: 'break-all' }}>{d.id}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <Empty>Ninguno: todo lo que gestionan los estados sigue en Azure.</Empty>}
            </Card>
          </Section>
          <Section title="Tags cambiadas a mano" description="Tag por tag: lo que declara Terraform y lo que tiene el recurso.">
            <Card flush>
              {data.tags.length ? (
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>Recurso</th><th>Tag</th><th>En Terraform</th><th>En Azure</th></tr></thead>
                    <tbody>
                      {data.tags.flatMap((r) => r.changes.map((c, n) => (
                        <tr key={`${r.uid}-${c.tag}`}>
                          <td>{n === 0 ? <button className="btn btn-ghost btn-sm" onClick={() => onRecurso(r.uid)}>{r.name}</button> : null}</td>
                          <td className="mono" style={{ fontSize: 12 }}>{c.tag}</td>
                          <td className="secondary">{c.terraform ?? <em>no la declara</em>}</td>
                          <td className="secondary">{c.real ?? <em>no la tiene</em>}</td>
                        </tr>
                      )))}
                    </tbody>
                  </table>
                </div>
              ) : <Empty>Ninguna: las tags de Azure coinciden con las de los estados.</Empty>}
            </Card>
          </Section>
        </div>
      )}
    </>
  );
}

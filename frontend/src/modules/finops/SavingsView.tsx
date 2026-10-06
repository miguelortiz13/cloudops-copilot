import { MessageSquare } from 'lucide-react';
import { get, scopeQuery } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { money, number, percent, shortType } from '../../lib/format';
import type { FinOpsReport, OrphanResource } from '../../lib/types';
import { useApp } from '../../state/hooks';
import { Badge, Card, Empty, ErrorState, Loading, Meter, Notice, Section, StatTile } from '../../components/ui';

const CATEGORIES: { key: keyof FinOpsReport; label: string; hint: (r: OrphanResource) => string }[] = [
  { key: 'unattached_disks', label: 'Disco sin VM', hint: (r) => `${r.sku ?? ''}${r.sizeGB ? ` · ${r.sizeGB} GB` : ''}` },
  { key: 'unassociated_ips', label: 'IP pública libre', hint: (r) => r.ipAddress ?? '' },
  { key: 'orphaned_nics', label: 'NIC sin VM', hint: () => '' },
  { key: 'empty_app_plans', label: 'App Service Plan vacío', hint: (r) => r.sku ?? '' },
  { key: 'old_snapshots', label: 'Snapshot antiguo', hint: (r) => (r.sizeGB ? `${r.sizeGB} GB` : '') },
];

/**
 * Optimización y ahorro: lo que se puede quitar, ajustar o comprometer.
 *
 * Va después de la vista de costos a propósito: cada oportunidad se lee mejor
 * sabiendo cuánto pesa sobre el gasto total.
 */
export function SavingsView() {
  const { scope, scopeKey, askAgent } = useApp();
  const { data, error, loading, refreshing, reload } = useApi<FinOpsReport>(
    `finops-report:${scopeKey}`,
    () => get<FinOpsReport>(`/api/finops/report${scopeQuery(scope)}`),
  );

  if (loading) return <Loading label="Analizando recursos sin uso y tarifas…" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  const currency = data.cost_data?.currency ?? 'USD';
  const lifecycle = data.savings_lifecycle;
  const orphans = CATEGORIES.flatMap((cat) =>
    ((data[cat.key] as OrphanResource[] | undefined) ?? []).map((r) => ({ ...r, category: cat.label, hint: cat.hint(r) })),
  ).sort((a, b) => (b.monthly_cost_usd ?? 0) - (a.monthly_cost_usd ?? 0));
  const insights = data.insights;
  const orphanTotal = orphans.reduce((s, r) => s + (r.monthly_cost_usd ?? 0), 0);

  return (
    <div className="stack" style={{ gap: 24 }}>
      {data.cost_data?.basis && data.cost_data.basis !== 'actual' && data.cost_data.message && (
        <Notice tone="warning">{data.cost_data.message}</Notice>
      )}

      <div className="grid grid-4">
        <StatTile
          refreshing={refreshing}
          label="Ahorro potencial mensual"
          value={money(lifecycle?.potential_savings_usd ?? 0, currency)}
          meta={lifecycle?.potential_from_estimate_usd
            ? `${money(lifecycle.potential_from_estimate_usd, currency)} estimado por tarifa`
            : 'sobre facturación real'}
        />
        <StatTile refreshing={refreshing} label="Recursos sin uso" value={number(orphans.length)} meta={`${money(orphanTotal, currency)} al mes`} />
        <StatTile
          refreshing={refreshing}
          label="Apagado programado"
          value={money(lifecycle?.schedule_savings_usd ?? 0, currency)}
          meta={`${insights?.running_dev_vms_outside_hours?.length ?? 0} VMs de dev/QA encendidas fuera de horario`}
        />
        <StatTile
          refreshing={refreshing}
          label="Reservas y Savings Plans"
          value={money(lifecycle?.reservation_savings_usd ?? 0, currency)}
          meta={`${insights?.reservation_recommendations?.length ?? 0} recomendaciones`}
        />
      </div>

      <Section
        title="Recursos sin uso"
        description="Se pueden eliminar sin afectar nada en marcha. El costo sale de la factura donde hay cobertura y de la tarifa de referencia donde no; cada fila dice cuál."
      >
        <Card flush refreshing={refreshing}>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Recurso</th><th>Categoría</th><th>Región</th>
                  <th className="num">Costo mensual</th><th>Origen</th><th />
                </tr>
              </thead>
              <tbody>
                {orphans.map((r) => (
                  <tr key={`${r.category}-${r.id ?? r.name}`}>
                    <td>
                      <span className="primary-cell">{r.name}</span>
                      <span className="sub">{r.resourceGroup}{r.hint ? ` · ${r.hint}` : ''}</span>
                    </td>
                    <td className="secondary">{r.category}</td>
                    <td className="secondary">{r.location ?? '—'}</td>
                    <td className="num primary-cell">{money(r.monthly_cost_usd ?? 0, currency)}</td>
                    <td>{r.cost_basis === 'actual' ? <Badge tone="accent">Facturado</Badge> : <Badge>Estimado</Badge>}</td>
                    <td>
                      <div className="row-actions">
                        <button
                          className="btn btn-ghost btn-sm btn-icon"
                          title="Analizar con el agente"
                          aria-label={`Analizar ${r.name}`}
                          onClick={() => askAgent('finops', `Analiza el recurso sin uso ${r.name} (${r.category}) en ${r.resourceGroup}. ¿Es seguro eliminarlo y cuánto ahorro?`)}
                        >
                          <MessageSquare size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {orphans.length === 0 && (
                  <tr><td colSpan={6} className="table-empty">No hay discos, IPs, NICs, planes ni snapshots sin uso.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </Section>

      <Section title="Uso y tarifa" description="Lo que no se elimina pero se paga de más: horarios, sobredimensionamiento y compromisos de tarifa.">
        <div className="grid grid-2">
          <Card title="VMs de dev/QA fuera de horario" flush refreshing={refreshing}>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>VM</th><th>Ambiente</th><th className="num">Ahorro estimado</th></tr></thead>
                <tbody>
                  {(insights?.running_dev_vms_outside_hours ?? []).map((v) => (
                    <tr key={v.name}>
                      <td><span className="primary-cell">{v.name}</span><span className="sub">{v.resourceGroup}</span></td>
                      <td className="secondary">{v.environment}</td>
                      <td className="num">{money(v.saving_potential, currency)}</td>
                    </tr>
                  ))}
                  {!insights?.running_dev_vms_outside_hours?.length && (
                    <tr><td colSpan={3} className="table-empty">Ninguna VM de dev/QA encendida fuera de horario.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="Right-sizing" subtitle="CPU promedio de 30 días desde Azure Monitor" flush refreshing={refreshing}>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>VM</th><th>Tamaño</th><th className="num">CPU</th><th className="num">Costo</th></tr></thead>
                <tbody>
                  {(insights?.underutilized_resources ?? []).map((u) => (
                    <tr key={u.name}>
                      <td className="primary-cell">{u.name}</td>
                      <td><code>{u.size}</code></td>
                      <td className="num">{percent(u.avg_cpu_percentage)}</td>
                      <td className="num">{money(u.monthly_cost_usd, currency)}</td>
                    </tr>
                  ))}
                  {!insights?.underutilized_resources?.length && (
                    <tr><td colSpan={4} className="table-empty">Sin VMs sobredimensionadas.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
        <Card title="Reservas y Savings Plans" flush refreshing={refreshing}>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Tipo</th><th>SKU</th><th className="num">Instancias</th><th>Opción</th><th className="num">Ahorro</th></tr></thead>
              <tbody>
                {(insights?.reservation_recommendations ?? []).map((r, i) => (
                  <tr key={i}>
                    <td>{r.resource_type}</td>
                    <td><code>{r.sku_size}</code></td>
                    <td className="num">{r.quantity_instances}</td>
                    <td className="secondary">{r.savings_plan_option}</td>
                    <td className="num">{percent(r.estimated_savings_percentage, 0)} · {money(r.monthly_saving_usd, currency)}</td>
                  </tr>
                ))}
                {!insights?.reservation_recommendations?.length && (
                  <tr><td colSpan={5} className="table-empty">Sin cargas estables que justifiquen un compromiso de tarifa.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </Section>

      <Section title="Control del gasto" description="Presupuestos, variaciones inusuales y recursos que no se pueden atribuir.">
        <div className="grid grid-2">
          <Card title="Presupuestos" subtitle="Consumo actual frente al límite definido en Azure" refreshing={refreshing}>
            {insights?.budgets?.length ? (
              <div className="stack">
                {insights.budgets.map((b, i) => (
                  <div key={i} className="stack" style={{ gap: 6 }}>
                    <div className="spread" style={{ fontSize: 13 }}>
                      <span className="truncate">{b.name ?? b.scope}</span>
                      <span className="num secondary">{money(b.current_spending, currency)} / {money(b.budget_limit, currency)}</span>
                    </div>
                    <Meter value={b.percentage_used} tone={b.percentage_used >= 100 ? 'critical' : b.percentage_used >= 80 ? 'warning' : undefined} />
                  </div>
                ))}
              </div>
            ) : (
              <Empty title="Sin presupuestos">No hay presupuestos definidos en las suscripciones del alcance. Crearlos en Cost Management habilita alertas tempranas.</Empty>
            )}
          </Card>
          <Card title="Variaciones del gasto" subtitle="Últimos 7 días frente a los 23 anteriores" refreshing={refreshing}>
            {insights?.anomalies?.length ? (
              <div className="stack">
                {insights.anomalies.map((a, i) => (
                  <div key={i} className="stack" style={{ gap: 2 }}>
                    <div className="row">
                      <span className={`dot ${a.severity === 'Critical' ? 'dot-critical' : a.severity === 'Warning' ? 'dot-warning' : 'dot-accent'}`} />
                      <strong style={{ fontSize: 13 }}>{a.title}</strong>
                    </div>
                    <span className="secondary" style={{ fontSize: 13 }}>{a.description}</span>
                    {a.recomm_action && <span className="muted" style={{ fontSize: 12.5 }}>{a.recomm_action}</span>}
                  </div>
                ))}
              </div>
            ) : (
              <Empty>Sin variaciones inusuales.</Empty>
            )}
          </Card>
        </div>
        <div className="grid grid-2">
          <Card title="Recursos sin ninguna etiqueta" subtitle="Su gasto no se puede atribuir a nadie" flush refreshing={refreshing}>
            <div className="table-wrap" style={{ maxHeight: 320, overflowY: 'auto' }}>
              <table className="table">
                <thead><tr><th>Recurso</th><th>Tipo</th></tr></thead>
                <tbody>
                  {data.untagged_resources.map((r) => (
                    <tr key={r.id ?? r.name}>
                      <td><span className="primary-cell">{r.name}</span><span className="sub">{r.resourceGroup}</span></td>
                      <td className="secondary">{shortType(r.type)}</td>
                    </tr>
                  ))}
                  {!data.untagged_resources.length && <tr><td colSpan={2} className="table-empty">Todos los recursos tienen etiquetas.</td></tr>}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="Temporales sin fecha de expiración" subtitle="Recursos de dev/QA sin tag ExpirationDate" flush refreshing={refreshing}>
            <div className="table-wrap" style={{ maxHeight: 320, overflowY: 'auto' }}>
              <table className="table">
                <thead><tr><th>Recurso</th><th>Tipo</th></tr></thead>
                <tbody>
                  {(insights?.aging_resources_no_expiration ?? []).map((r) => (
                    <tr key={r.name}>
                      <td><span className="primary-cell">{r.name}</span><span className="sub">{r.resourceGroup}</span></td>
                      <td className="secondary">{shortType(r.type)}</td>
                    </tr>
                  ))}
                  {!insights?.aging_resources_no_expiration?.length && (
                    <tr><td colSpan={2} className="table-empty">Ningún recurso temporal sin fecha de expiración.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      </Section>
    </div>
  );
}

import { ArrowRight } from 'lucide-react';
import { get, post, scopeQuery } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { money, number, percent } from '../../lib/format';
import type { CostOverview, InventorySummary, RiskExposure, SecOpsReport, TagCompliance, TerraformCoverage } from '../../lib/types';
import { useApp } from '../../state/hooks';
import { BarList, DailyCostChart } from '../../components/charts';
import { Card, Delta, Empty, Loading, Meter, PageHeader, SeverityBadge, StatTile } from '../../components/ui';

function Go({ to, label }: { to: string; label: string }) {
  return <a className="btn btn-ghost btn-sm" href={`#/${to}`}>{label} <ArrowRight size={13} /></a>;
}

/**
 * Resumen ejecutivo: una pantalla para saber cómo está la nube.
 *
 * Cada tarjeta resume un módulo y enlaza a él. No hay cifras propias: todo
 * sale de los mismos endpoints que alimentan cada sección.
 */
export function OverviewPage() {
  const { scope, scopeKey } = useApp();
  const costs = useApi<CostOverview>(`costs:${scopeKey}`, () => get(`/api/finops/costs${scopeQuery(scope)}`));
  const summary = useApi<InventorySummary>(`inv-summary:${scopeKey}`, () => post('/api/inventory/summary', { subscriptionIds: scope }));
  const tags = useApi<TagCompliance>(`inv-tags:${scopeKey}`, () => post('/api/inventory/tag-compliance', { subscriptionIds: scope }));
  const secops = useApi<SecOpsReport>(`secops:${scopeKey}`, () => get(`/api/secops/report${scopeQuery(scope)}`));
  const exposure = useApi<RiskExposure>(`exposure:${scopeKey}`, () => get(`/api/secops/exposure${scopeQuery(scope)}`));
  const tf = useApi<TerraformCoverage>(`tfcov:${scopeKey}`, () => post('/api/iac/terraform-coverage', { subscriptionIds: scope }));

  const c = costs.data;
  const s = summary.data;
  const sev = secops.data?.severity_summary;

  return (
    <>
      <PageHeader
        title="Resumen"
        description="Gasto, gobernanza, seguridad y cobertura de IaC de las suscripciones del alcance, en una sola vista."
      />

      <div className="grid kpi-grid">
        <StatTile
          hero
          refreshing={costs.refreshing}
          label="Gasto de los últimos 30 días"
          value={c ? money(c.totals.last_period, c.currency) : '—'}
          delta={c ? <Delta value={c.totals.delta_percentage} polarity="up-bad" label="vs. periodo anterior" /> : undefined}
          meta={c?.totals.forecast_month != null ? `Proyección del mes: ${money(c.totals.forecast_month, c.currency)}` : undefined}
        />
        <StatTile
          refreshing={summary.refreshing}
          label="Cumplimiento de tags"
          value={s ? percent(s.tagCompliancePercentage) : '—'}
          meta={s ? `${number(s.nonCompliantResources)} de ${number(s.totalResources)} recursos incompletos` : undefined}
        />
        <StatTile
          refreshing={secops.refreshing}
          label="Hallazgos de seguridad"
          value={sev ? number(sev.critica + sev.alta + sev.media) : '—'}
          meta={sev ? <><span className="dot dot-critical" style={{ display: 'inline-block', marginRight: 4 }} />{sev.critica} críticos · {sev.alta} altos</> : undefined}
        />
        <StatTile
          refreshing={tf.refreshing}
          label="Gestionado por Terraform"
          value={tf.data?.available ? percent(tf.data.coverage_percentage) : '—'}
          meta={tf.data?.available ? `${number(tf.data.managed_in_inventory)} de ${number(tf.data.total_resources)} recursos` : tf.data?.message}
        />
      </div>

      <div className="grid grid-main-side">
        <Card title="Gasto diario" subtitle="Últimos 60 días" actions={<Go to="finops" label="Ver costos" />} refreshing={costs.refreshing}>
          {c ? <DailyCostChart data={c.daily} currency={c.currency} height={180} /> : costs.loading ? <Loading /> : <Empty>Sin datos de costos.</Empty>}
        </Card>
        <Card title="En qué se va el gasto" subtitle="Por servicio, últimos 30 días" refreshing={costs.refreshing}>
          {c ? <BarList items={c.by_service.slice(0, 6)} currency={c.currency} /> : costs.loading ? <Loading /> : <Empty>Sin datos.</Empty>}
        </Card>
      </div>

      <div className="grid grid-2">
        <Card title="Prioridades de seguridad" subtitle="Los hallazgos que hay que atender primero" actions={<Go to="secops" label="Ver seguridad" />} flush refreshing={exposure.refreshing}>
          {exposure.data ? (
            <div className="table-wrap">
              <table className="table">
                <tbody>
                  {exposure.data.findings.slice(0, 5).map((f, i) => (
                    <tr key={`${f.id}-${i}`}>
                      <td style={{ width: 110 }}><SeverityBadge severity={f.severidad} /></td>
                      <td><span className="primary-cell">{f.titulo}</span><span className="sub">{f.name}</span></td>
                    </tr>
                  ))}
                  {!exposure.data.findings.length && <tr><td className="table-empty">Sin hallazgos de seguridad.</td></tr>}
                </tbody>
              </table>
            </div>
          ) : <Loading />}
        </Card>
        <Card title="Gobernanza" subtitle="Tags obligatorias y recursos sin control" actions={<Go to="inventario" label="Ver inventario" />} refreshing={tags.refreshing}>
          {tags.data && s ? (
            <div className="stack">
              {tags.data.matrix.map((m) => (
                <div key={m.tag} className="stack" style={{ gap: 6 }}>
                  <div className="spread" style={{ fontSize: 13 }}>
                    <span className="mono">{m.tag}</span>
                    <span className="num secondary">{percent(m.compliancePercentage)}</span>
                  </div>
                  <Meter value={m.compliancePercentage} tone={m.compliancePercentage >= 90 ? 'good' : m.compliancePercentage >= 60 ? 'warning' : 'critical'} />
                </div>
              ))}
              <div className="divider" />
              <div className="spread" style={{ fontSize: 13 }}>
                <span className="secondary">Candidatos a Shadow IT</span><strong className="num">{number(s.shadowItCandidates)}</strong>
              </div>
              <div className="spread" style={{ fontSize: 13 }}>
                <span className="secondary">Sin custodio identificable</span><strong className="num">{number(s.resourcesWithoutOwnerCandidate)}</strong>
              </div>
            </div>
          ) : <Loading />}
        </Card>
      </div>
    </>
  );
}

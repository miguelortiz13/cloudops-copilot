import { useState } from 'react';
import { MessageSquare } from 'lucide-react';
import { get, scopeQuery } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { money, number } from '../../lib/format';
import type { Finding, RiskExposure, SecOpsReport, Severity } from '../../lib/types';
import { useApp } from '../../state/hooks';
import {
  Card, ErrorState, Loading, Notice, PageHeader, Section, Segmented, SeverityBadge, StatTile,
} from '../../components/ui';

/**
 * Reglas evaluadas por SecOps (services/secops_service.py). El conteo sale de
 * la lista de hallazgos, así que una regla nueva en el backend aparece aquí sin
 * tocar el panel; las que no tienen hallazgos se listan igual, en cero.
 */
const RULES: { tipo: string; label: string }[] = [
  { tipo: 'nsg', label: 'Puertos de administración abiertos' },
  { tipo: 'storage', label: 'Storage con blobs públicos' },
  { tipo: 'keyvault', label: 'Key Vaults en red pública' },
  { tipo: 'sql', label: 'SQL con acceso público' },
  { tipo: 'https', label: 'App Service sin HTTPS obligatorio' },
  { tipo: 'disco', label: 'Discos sin llave del cliente' },
  { tipo: 'failed', label: 'Recursos en estado Failed' },
];

function CostCell({ f, currency }: { f: Finding; currency: string }) {
  if (f.cost_basis === 'actual') return <span className="num">{money(f.monthly_cost_usd ?? 0, currency)}</span>;
  if (f.cost_basis === 'not_applicable') return <span className="muted" title="El costo no es atribuible a esta regla">No aplica</span>;
  return <span className="muted" title="Su suscripción no tiene cobertura de costos">Desconocido</span>;
}

export function SecOpsPage() {
  const { scope, scopeKey, askAgent } = useApp();
  const exposure = useApi<RiskExposure>(`exposure:${scopeKey}`, () => get(`/api/secops/exposure${scopeQuery(scope)}`));
  const report = useApi<SecOpsReport>(`secops:${scopeKey}`, () => get(`/api/secops/report${scopeQuery(scope)}`));
  const [sev, setSev] = useState<'all' | Severity>('all');

  const e = exposure.data;
  const counts = report.data?.severity_summary ?? { critica: 0, alta: 0, media: 0 };
  const findings = (e?.findings ?? []).filter((f) => sev === 'all' || f.severidad === sev);
  const currency = e?.totals.currency ?? 'USD';

  return (
    <>
      <PageHeader
        title="Seguridad"
        description="Hallazgos de exposición y salud operativa, ordenados por severidad y, dentro de cada severidad, por el gasto del recurso expuesto."
      />

      {exposure.loading && <Loading label="Evaluando la postura de seguridad…" />}
      {exposure.error && !e && <ErrorState error={exposure.error} onRetry={exposure.reload} />}

      {e && (
        <>
          <div className="grid grid-4">
            <StatTile refreshing={exposure.refreshing} icon={<span className="dot dot-critical" />} label="Críticos" value={number(counts.critica)} meta="Alcanzables desde internet" />
            <StatTile refreshing={exposure.refreshing} icon={<span className="dot dot-serious" />} label="Altos" value={number(counts.alta)} meta="Exposición sin vía directa confirmada" />
            <StatTile refreshing={exposure.refreshing} icon={<span className="dot dot-warning" />} label="Medios" value={number(counts.media)} meta="Higiene y salud operativa" />
            <StatTile
              refreshing={exposure.refreshing}
              label="Gasto mensual expuesto"
              value={money(e.totals.monthly_usd_at_risk, currency)}
              meta={`${number(e.totals.affected_resources)} recursos · ${number(e.totals.unmeasured_resources)} sin costo conocido`}
            />
          </div>

          {e.coverage.status !== 'success' && <Notice>{e.coverage.message}</Notice>}

          <div className="grid grid-main-side">
            <Section
              title="Hallazgos priorizados"
              description="La severidad manda; el dinero desempata. Un recurso sin costo conocido no vale cero."
              actions={
                <Segmented label="Severidad" value={sev} onChange={setSev} options={[
                  { id: 'all', label: `Todos (${e.findings.length})` },
                  { id: 'critica', label: 'Críticos' },
                  { id: 'alta', label: 'Altos' },
                  { id: 'media', label: 'Medios' },
                ]} />
              }
            >
              <Card flush refreshing={exposure.refreshing}>
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr><th>Severidad</th><th>Hallazgo</th><th className="num">Gasto mensual</th><th /></tr>
                    </thead>
                    <tbody>
                      {findings.map((f, i) => (
                        <tr key={`${f.id}-${f.titulo}-${i}`}>
                          <td style={{ width: 110 }}><SeverityBadge severity={f.severidad} /></td>
                          <td>
                            <span className="primary-cell">{f.titulo}</span>
                            <span className="sub">{f.name}{f.resourceGroup ? ` · ${f.resourceGroup}` : ''}</span>
                            {f.recomendacion && <span className="sub" style={{ marginTop: 2 }}>{f.recomendacion}</span>}
                          </td>
                          <td className="num"><CostCell f={f} currency={currency} /></td>
                          <td>
                            <div className="row-actions">
                              <button
                                className="btn btn-ghost btn-sm btn-icon"
                                title="Pedir la remediación al agente"
                                aria-label={`Remediar ${f.name}`}
                                onClick={() => askAgent('secops', `Hallazgo "${f.titulo}" en ${f.name} (grupo ${f.resourceGroup}). Dame los pasos y comandos de Azure CLI para remediarlo.`)}
                              >
                                <MessageSquare size={14} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                      {findings.length === 0 && (
                        <tr><td colSpan={4} className="table-empty">Sin hallazgos{sev !== 'all' ? ' de esta severidad' : ''}.</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </Card>
            </Section>

            <Section title="Reglas evaluadas" description="Hallazgos por regla en el alcance actual.">
              <Card refreshing={report.refreshing}>
                <div className="stack" style={{ gap: 0 }}>
                  {RULES.map((s, i) => {
                    const n = (report.data?.findings ?? []).filter((f) => f.tipo === s.tipo).length;
                    return (
                      <div key={s.tipo} className="spread" style={{ padding: '10px 0', borderTop: i ? '1px solid var(--border)' : 0, fontSize: 13 }}>
                        <span className={n ? '' : 'muted'}>{s.label}</span>
                        <strong className="num">{number(n)}</strong>
                      </div>
                    );
                  })}
                </div>
              </Card>
            </Section>
          </div>
        </>
      )}
    </>
  );
}

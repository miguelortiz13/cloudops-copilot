import { useState } from 'react';
import { MessageSquare } from 'lucide-react';
import { get, scopeQuery } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateRange, money, number, shortType } from '../../lib/format';
import type { CostGroup, CostOverview } from '../../lib/types';
import { useApp } from '../../state/hooks';
import { BarList, DailyCostChart, DailyCostTable } from '../../components/charts';
import {
  Badge, Card, Delta, Empty, ErrorState, Loading, Meter, Notice, Section, Segmented, StatTile,
} from '../../components/ui';

type Dimension = 'service' | 'resource_group' | 'subscription' | 'location';

const DIMENSIONS: { id: Dimension; label: string }[] = [
  { id: 'service', label: 'Servicio' },
  { id: 'resource_group', label: 'Grupo de recursos' },
  { id: 'subscription', label: 'Suscripción' },
  { id: 'location', label: 'Región' },
];

function groupsFor(data: CostOverview, dim: Dimension): CostGroup[] {
  switch (dim) {
    case 'service': return data.by_service;
    case 'resource_group': return data.by_resource_group;
    case 'subscription': return data.by_subscription;
    case 'location': return data.by_location;
  }
}

function freshness(seconds: number): string {
  if (!seconds) return 'recién consultado';
  const min = Math.round(seconds / 60);
  if (min < 60) return `caché de hace ${min} min`;
  return `caché de hace ${Math.round(min / 60)} h`;
}

/**
 * Vista global de costos: lo primero que se ve en FinOps.
 *
 * Responde, en este orden, cuánto se gasta, cómo evoluciona y en qué se va.
 * El ahorro viene después, en su propia pestaña: una oportunidad de 3 USD
 * solo se puede juzgar sabiendo si la cuenta es de 30 o de 30.000.
 */
export function CostsView() {
  const { scope, scopeKey, askAgent } = useApp();
  const { data, error, loading, refreshing, reload } = useApi<CostOverview>(
    `costs:${scopeKey}`,
    () => get<CostOverview>(`/api/finops/costs${scopeQuery(scope)}`),
  );
  const [dimension, setDimension] = useState<Dimension>('service');
  const [dailyView, setDailyView] = useState<'chart' | 'table'>('chart');
  const tagKeys = data ? Object.keys(data.by_tag) : [];
  const [tag, setTag] = useState<string | null>(null);
  const activeTag = tag && tagKeys.includes(tag) ? tag : tagKeys[0];

  if (loading) return <Loading label="Consultando la facturación de Azure…" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  const t = data.totals;
  const c = data.currency;
  const unattributedTag = activeTag
    ? data.by_tag[activeTag]?.find((g) => g.key === `Sin ${activeTag}`)
    : undefined;

  return (
    <div className="stack" style={{ gap: 24 }}>
      {data.basis !== 'actual' && (
        <Notice tone={data.basis === 'unavailable' ? 'critical' : 'warning'}>
          <strong>{data.basis === 'unavailable' ? 'Sin facturación' : 'Cobertura parcial'}.</strong>{' '}
          {data.message}
          {data.coverage.uncovered_names.length > 0 && <> Fuera del total: {data.coverage.uncovered_names.join(', ')}.</>}
        </Notice>
      )}

      <div className="grid kpi-grid">
        <StatTile
          hero
          refreshing={refreshing}
          label={`Gasto de los últimos ${t.period_days} días`}
          value={money(t.last_period, c)}
          delta={<Delta value={t.delta_percentage} polarity="up-bad" label="vs. 30 días anteriores" />}
          meta={t.period_start && t.period_end ? dateRange(t.period_start, t.period_end) : undefined}
        />
        <StatTile
          refreshing={refreshing}
          label="Mes en curso"
          value={money(t.month_to_date, c)}
          meta={t.forecast_month !== null ? <>Proyección al cierre: <strong className="secondary">{money(t.forecast_month, c)}</strong></> : undefined}
        />
        <StatTile
          refreshing={refreshing}
          label="Promedio diario"
          value={money(t.daily_average, c)}
          meta={t.previous_period !== null ? `Periodo anterior: ${money(t.previous_period, c)}` : undefined}
        />
        <StatTile
          refreshing={refreshing}
          label="Recursos con gasto"
          value={number(t.resources_with_cost)}
          meta={t.deleted_resources_with_cost > 0 ? `${t.deleted_resources_with_cost} ya eliminados facturaron en el periodo` : 'en la ventana de 30 días'}
        />
      </div>

      <Card
        title="Evolución del gasto diario"
        subtitle="Facturación real por día. Azure Cost Management consolida con 24 a 48 horas de retraso."
        refreshing={refreshing}
        actions={
          <Segmented
            label="Vista"
            value={dailyView}
            onChange={setDailyView}
            options={[{ id: 'chart', label: 'Gráfico' }, { id: 'table', label: 'Tabla' }]}
          />
        }
      >
        {data.daily.length === 0
          ? <Empty title="Sin serie diaria">Cost Management no devolvió la serie diaria para este alcance.</Empty>
          : dailyView === 'chart'
            ? <DailyCostChart data={data.daily} currency={c} highlightLast={t.period_days} />
            : <DailyCostTable data={data.daily} currency={c} />}
      </Card>

      <div className="grid grid-main-side">
        <Card
          title="Distribución del gasto"
          subtitle={`Últimos ${t.period_days} días`}
          refreshing={refreshing}
          actions={<Segmented label="Dimensión" value={dimension} onChange={setDimension} options={DIMENSIONS} />}
        >
          <BarList items={groupsFor(data, dimension)} currency={c} emptyText="Sin gasto atribuible a recursos." />
        </Card>

        <Card
          title="Atribución por etiqueta"
          subtitle="Showback según las tags de cada recurso"
          refreshing={refreshing}
          actions={tagKeys.length > 1 && activeTag ? (
            <Segmented label="Etiqueta" value={activeTag} onChange={setTag} options={tagKeys.map((k) => ({ id: k, label: k }))} />
          ) : undefined}
        >
          {activeTag ? (
            <div className="stack">
              <BarList items={data.by_tag[activeTag] ?? []} currency={c} />
              {unattributedTag && (
                <div className="stack" style={{ gap: 6 }}>
                  <div className="spread" style={{ fontSize: 12.5 }}>
                    <span className="secondary">Gasto sin la etiqueta <code>{activeTag}</code></span>
                    <strong className="num">{unattributedTag.share.toLocaleString('es-CO')} %</strong>
                  </div>
                  <Meter value={unattributedTag.share} tone={unattributedTag.share > 25 ? 'warning' : undefined} />
                </div>
              )}
            </div>
          ) : (
            <Empty>No hay etiquetas de showback configuradas (SHOWBACK_TAGS).</Empty>
          )}
        </Card>
      </div>

      <Section
        title="Recursos con mayor gasto"
        description={`Los ${data.top_resources.length} recursos más costosos de los últimos ${t.period_days} días, con su peso sobre el total.`}
      >
        <Card flush refreshing={refreshing}>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Recurso</th>
                  <th>Servicio</th>
                  <th>Suscripción</th>
                  {tagKeys.slice(0, 1).map((k) => <th key={k}>{k}</th>)}
                  <th className="num">Gasto</th>
                  <th style={{ width: 140 }}>% del total</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.top_resources.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <span className="primary-cell">{r.name}</span>
                      {r.deleted && <> <Badge>Eliminado</Badge></>}
                      <span className="sub">{r.resourceGroup} · {shortType(r.type)}</span>
                    </td>
                    <td className="secondary">{r.service}</td>
                    <td className="secondary">{r.subscriptionName}</td>
                    {tagKeys.slice(0, 1).map((k) => (
                      <td key={k} className={r.tags[k] ? '' : 'muted'}>{r.tags[k] ?? 'Sin etiqueta'}</td>
                    ))}
                    <td className="num primary-cell">{money(r.cost, c)}</td>
                    <td>
                      <div className="row" style={{ gap: 8 }}>
                        <div style={{ flex: 1 }}><Meter value={r.share} /></div>
                        <span className="num muted" style={{ fontSize: 12, minWidth: 40, textAlign: 'right' }}>
                          {r.share.toLocaleString('es-CO')} %
                        </span>
                      </div>
                    </td>
                    <td>
                      <div className="row-actions">
                        <button
                          className="btn btn-ghost btn-sm btn-icon"
                          title="Preguntar al agente de costos"
                          aria-label={`Preguntar por ${r.name}`}
                          onClick={() => askAgent('finops', `¿Por qué ${r.name} (${r.service}, grupo ${r.resourceGroup}) cuesta ${money(r.cost, c)} en 30 días y cómo puedo reducirlo?`)}
                        >
                          <MessageSquare size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {data.top_resources.length === 0 && (
                  <tr><td colSpan={7} className="table-empty">No hay recursos con gasto facturado en el periodo.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </Section>

      <div className="muted" style={{ fontSize: 12.5 }}>
        {data.message} · {freshness(data.cache_age_seconds)}
        {t.unassigned_charges > 0 && <> · {money(t.unassigned_charges, c)} en cargos que no pertenecen a un recurso (soporte, Marketplace, reservas)</>}
        {t.forecast_month !== null && <> · La proyección es lineal con el promedio de los últimos 7 días</>}
      </div>
    </div>
  );
}

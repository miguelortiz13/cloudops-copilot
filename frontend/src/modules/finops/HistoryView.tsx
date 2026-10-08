import { useState } from 'react';
import { get } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateRange, dateTime, day, money, shortType } from '../../lib/format';
import type { CostHistory, CostPeriod } from '../../lib/types';
import { BarList, DailyCostChart, DailyCostTable, MonthlyCostChart } from '../../components/charts';
import {
  Badge, Card, Delta, Empty, ErrorState, Loading, Meter, Notice, Section, Segmented, StatTile,
} from '../../components/ui';

const PERIODS: { id: CostPeriod; label: string; compare: string }[] = [
  { id: 'mtd', label: 'Mes en curso', compare: 'vs. mismos días del mes anterior' },
  { id: 'last_month', label: 'Mes anterior', compare: 'vs. el mes previo' },
  { id: '7d', label: '7 días', compare: 'vs. 7 días anteriores' },
  { id: '30d', label: '30 días', compare: 'vs. 30 días anteriores' },
  { id: '90d', label: '90 días', compare: 'vs. 90 días anteriores' },
];

type Dimension = 'service' | 'account';

/**
 * Historia de costos desde la base de la plataforma.
 *
 * A diferencia de la visión general (consulta en vivo a Cost Management), esta
 * vista lee lo que guarda el recolector diario: permite elegir periodo y
 * comparar mes a mes sin depender de los límites de la API de Azure. Cubre
 * todas las suscripciones que ve la plataforma; el selector de alcance no la
 * filtra todavía.
 */
export function HistoryView() {
  const [period, setPeriod] = useState<CostPeriod>('mtd');
  const [dimension, setDimension] = useState<Dimension>('service');
  const [dailyView, setDailyView] = useState<'chart' | 'table'>('chart');
  const { data, error, loading, refreshing, reload } = useApi<CostHistory>(
    `cost-history:${period}`,
    () => get<CostHistory>(`/api/history/costs?period=${period}`),
  );
  const meta = PERIODS.find((p) => p.id === period)!;

  const selector = (
    <Segmented label="Periodo" value={period} onChange={setPeriod} options={PERIODS.map(({ id, label }) => ({ id, label }))} />
  );

  if (loading) return <Loading label="Leyendo la historia de costos…" />;
  if (error && !data) {
    return (
      <div className="stack">
        <Notice tone="warning">
          <strong>La historia no está disponible.</strong> {error}. La visión general sigue funcionando con datos en vivo de Azure.
        </Notice>
        <ErrorState error={error} onRetry={reload} />
      </div>
    );
  }
  if (!data) return null;
  if (!data.available) {
    return <Empty title="Todavía no hay historia">{data.message} El recolector diario la llena a las 06:00 UTC.</Empty>;
  }

  const c = data.currency;
  // Medio centavo o menos se muestra como 0,00: no aporta en el ranking.
  const recursos = data.by_resource.filter((r) => r.cost >= 0.005);
  const days = data.daily.length || 1;
  const groups = dimension === 'service'
    ? data.by_service.map((g) => ({ ...g, key: g.key || 'Sin servicio' }))
    : data.by_account.map((g) => ({ ...g, key: g.name }));

  return (
    <div className="stack" style={{ gap: 24 }}>
      <div className="spread" style={{ flexWrap: 'wrap', gap: 12 }}>
        {selector}
        <span className="muted" style={{ fontSize: 12.5 }}>
          Todas las suscripciones · datos hasta el {day(data.data_through)}
        </span>
      </div>

      <div className="grid kpi-grid">
        <StatTile
          hero
          refreshing={refreshing}
          label={meta.label}
          value={money(data.total, c)}
          delta={data.previous_complete
            ? <Delta value={data.delta_percentage} polarity="up-bad" label={meta.compare} />
            : undefined}
          meta={dateRange(data.from, data.to)}
        />
        <StatTile
          refreshing={refreshing}
          label="Periodo de comparación"
          value={data.previous_complete ? money(data.previous_total, c) : 'Sin datos'}
          meta={data.previous_complete
            ? dateRange(data.previous_from, data.previous_to)
            : `La base tiene costos desde el ${day(data.data_from ?? data.from)}`}
        />
        <StatTile refreshing={refreshing} label="Promedio diario" value={money(data.total / days, c)} meta={`${days} días`} />
        <StatTile
          refreshing={refreshing}
          label="Servicio principal"
          value={data.by_service[0]?.key || '—'}
          meta={data.by_service[0] ? `${money(data.by_service[0].cost, c)} · ${data.by_service[0].share.toLocaleString('es-CO')} %` : undefined}
        />
      </div>

      <div className="grid grid-main-side">
        <Card
          title="Gasto diario del periodo"
          subtitle={dateRange(data.from, data.to)}
          refreshing={refreshing}
          actions={
            <Segmented label="Vista" value={dailyView} onChange={setDailyView}
              options={[{ id: 'chart', label: 'Gráfico' }, { id: 'table', label: 'Tabla' }]} />
          }
        >
          {dailyView === 'chart'
            ? <DailyCostChart data={data.daily} currency={c} highlightLast={data.daily.length} />
            : <DailyCostTable data={data.daily} currency={c} />}
        </Card>
        <Card title="Mes a mes" subtitle="Últimos 13 meses guardados en la base" refreshing={refreshing}>
          {data.by_month.length > 0
            ? <MonthlyCostChart data={data.by_month} currency={c} partialLast={data.by_month[data.by_month.length - 1]?.month === data.data_through.slice(0, 7)} />
            : <Empty>Sin meses completos todavía.</Empty>}
        </Card>
      </div>

      <div className="grid grid-main-side">
        <Section
          title="Recursos con mayor gasto"
          description={`Los ${recursos.length} recursos más costosos del periodo.`}
        >
          <Card flush refreshing={refreshing}>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr><th>Recurso</th><th>Suscripción</th><th className="num">Gasto</th><th style={{ width: 140 }}>% del total</th></tr>
                </thead>
                <tbody>
                  {recursos.map((r) => (
                    <tr key={r.key || 'sin-recurso'}>
                      <td>
                        <span className="primary-cell">{r.name}</span>
                        {r.deleted && <> <Badge>Eliminado</Badge></>}
                        {(r.group || r.type) && <span className="sub">{[r.group, r.type && shortType(r.type)].filter(Boolean).join(' · ')}</span>}
                      </td>
                      <td className="secondary">{r.account ?? '—'}</td>
                      <td className="num primary-cell">{money(r.cost, c)}</td>
                      <td>
                        <div className="row" style={{ gap: 8 }}>
                          <div style={{ flex: 1 }}><Meter value={r.share} /></div>
                          <span className="num muted" style={{ fontSize: 12, minWidth: 40, textAlign: 'right' }}>{r.share.toLocaleString('es-CO')} %</span>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {recursos.length === 0 && (
                    <tr><td colSpan={4} className="table-empty">Sin gasto en el periodo.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </Section>

        <Section title="Distribución">
          <Card
            refreshing={refreshing}
            actions={<Segmented label="Dimensión" value={dimension} onChange={setDimension}
              options={[{ id: 'service', label: 'Servicio' }, { id: 'account', label: 'Suscripción' }]} />}
          >
            <BarList items={groups} currency={c} emptyText="Sin gasto en el periodo." />
          </Card>
        </Section>
      </div>

      <div className="muted" style={{ fontSize: 12.5 }}>
        Facturación real guardada por el recolector diario
        {data.collected_at && <> · última recolección {dateTime(data.collected_at)}</>}
        {' '}· Cost Management corrige los últimos días durante unas 72 horas; el recolector los vuelve a leer cada día.
      </div>
    </div>
  );
}

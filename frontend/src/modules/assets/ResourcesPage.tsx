import { useState } from 'react';
import { Search, Sparkles } from 'lucide-react';
import { get, post } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, money, number } from '../../lib/format';
import { Markdown } from '../../lib/markdown';
import { useApp } from '../../state/hooks';
import { BarList, DailyCostChart } from '../../components/charts';
import {
  Badge, Card, Empty, ErrorState, Loading, Notice, PageHeader, Pagination, Section, Segmented, SeverityBadge, StatTile,
} from '../../components/ui';
import type { Severity } from '../../lib/types';

interface Recurso {
  uid: string; provider: string; account_uid: string; account: string; name: string; type: string | null;
  region: string | null; cost_30d: number | null; currency: string | null; in_iac: boolean | null; classification: string | null;
}
interface Ficha {
  uid: string; name: string; provider: string; type: string; native_type: string; region: string | null; group: string | null;
  account: { uid: string; name: string }; tags: Record<string, string>; missing_tags: string[]; in_iac: boolean | null;
  created_by: string | null; first_seen: string; last_seen: string; deleted_at: string | null;
  cost: { total_30d: number; currency: string | null; daily: { date: string; cost: number }[]; by_service: { service: string; cost: number }[] };
  findings: { id: number; title: string; severity: Severity; status: string; owner: string | null; accepted_until: string | null; remediation: string | null }[];
  open_findings: number;
  classification: { classification: string; confidentiality: number; integrity: number; availability: number; custodian: string | null } | null;
  cluster: string | null;
  incidents: { id: number; title: string; severity: Severity; status: string; opened_at: string }[];
  timeline: { at: string; kind: string; actor: string; text: string }[];
}

const NUBE: Record<string, string> = { azure: 'Azure', aws: 'AWS', kubernetes: 'Kubernetes' };
const POR_PAGINA = 50;

function Terraform({ v }: { v: boolean | null }) {
  if (v === null) return <span className="secondary">Sin dato</span>;
  return <span className="badge"><span className={`dot ${v ? 'dot-good' : 'dot-warning'}`} aria-hidden="true" />{v ? 'En Terraform' : 'Fuera de Terraform'}</span>;
}

/**
 * Activos → Recursos: todo el inventario de Azure, AWS y Kubernetes (de la caché, sin despertar la base) y,
 * al elegir uno, su ficha única. Fase 3 del plan 10.
 */
export function ResourcesPage({ uid, onRecurso, onGo }: { uid?: string; onRecurso: (uid: string | null) => void; onGo: (path: string) => void }) {
  if (uid) return <FichaRecurso uid={decodeURIComponent(uid)} onVolver={() => onRecurso(null)} onGo={onGo} />;
  return <Lista onRecurso={onRecurso} />;
}

function Lista({ onRecurso }: { onRecurso: (uid: string) => void }) {
  const [q, setQ] = useState('');
  const [nube, setNube] = useState('');
  const [iac, setIac] = useState<'' | 'true' | 'false'>('');
  const [pagina, setPagina] = useState(1);
  const params = new URLSearchParams({ q, nube, pagina: String(pagina), por_pagina: String(POR_PAGINA) });
  if (iac) params.set('en_terraform', iac);
  const { data, error, loading, refreshing, reload } = useApi<{ total: number; items: Recurso[]; providers: string[] }>(
    `activos-recursos?${params}`, () => get(`/api/activos/recursos?${params}`));
  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  const filtro = (f: () => void) => { f(); setPagina(1); };

  return (
    <>
      <PageHeader title="Recursos" description="Todo el inventario de Azure, AWS y Kubernetes que guarda la plataforma, ordenado por gasto. Cada recurso tiene su ficha: gasto, hallazgos, clasificación, incidentes y línea de tiempo." />
      <div className="toolbar" style={{ marginBottom: 12 }}>
        <div className="input-icon grow">
          <Search size={14} />
          <input className="input" aria-label="Buscar" placeholder="Buscar por nombre, tipo o creador" value={q} onChange={(e) => filtro(() => setQ(e.target.value))} />
        </div>
        <Segmented label="Nube" value={nube} onChange={(v) => filtro(() => setNube(v))}
          options={[{ id: '', label: 'Todas' }, ...(data?.providers ?? []).map((p) => ({ id: p, label: NUBE[p] ?? p }))]} />
        <select className="select" aria-label="Terraform" value={iac} onChange={(e) => filtro(() => setIac(e.target.value as '' | 'true' | 'false'))}>
          <option value="">Con y sin Terraform</option><option value="true">En Terraform</option><option value="false">Fuera de Terraform</option>
        </select>
      </div>
      <Card flush refreshing={refreshing}>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Recurso</th><th>Nube</th><th>Cuenta</th><th className="num">Gasto 30 días</th><th>Terraform</th></tr></thead>
            <tbody>
              {(data?.items ?? []).map((r) => (
                <tr key={r.uid}>
                  <td>
                    <button className="btn btn-ghost btn-sm" onClick={() => onRecurso(r.uid)}>{r.name}</button>
                    <div className="secondary" style={{ fontSize: 12, paddingLeft: 8 }}>{r.type ?? '—'}{r.region ? ` · ${r.region}` : ''}</div>
                  </td>
                  <td className="secondary">{NUBE[r.provider] ?? r.provider}</td>
                  <td className="secondary">{r.account}</td>
                  <td className="num">{r.cost_30d === null ? '—' : money(r.cost_30d, r.currency ?? 'USD', 2)}</td>
                  <td><Terraform v={r.in_iac} /></td>
                </tr>
              ))}
              {data && data.items.length === 0 && <tr><td colSpan={5} className="table-empty">Ningún recurso coincide con los filtros.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
      {data && data.total > POR_PAGINA && <Pagination page={pagina} pageSize={POR_PAGINA} total={data.total} onPage={setPagina} />}
    </>
  );
}

function FichaRecurso({ uid, onVolver, onGo }: { uid: string; onVolver: () => void; onGo: (path: string) => void }) {
  const { toast } = useApp();
  const { data, error, loading, reload } = useApi<Ficha>(`activos-ficha-${uid}`, () => get(`/api/activos/ficha?uid=${encodeURIComponent(uid)}`));
  const [explicacion, setExplicacion] = useState<string | null>(null);
  const [pensando, setPensando] = useState(false);
  if (loading) return <Loading label="Armando la ficha (puede tardar un minuto si la base estaba pausada)…" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  const moneda = data.cost.currency ?? 'USD';

  const explicar = async () => {
    setPensando(true);
    try {
      const r = await post<{ explanation: string }>('/api/activos/ficha/explicacion', { uid });
      setExplicacion(r.explanation);
    } catch (e) {
      toast(`No se pudo explicar: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setPensando(false);
    }
  };

  return (
    <>
      <PageHeader title={data.name}
        description={`${NUBE[data.provider] ?? data.provider} · ${data.type} · ${data.account.name}${data.region ? ` · ${data.region}` : ''}${data.group ? ` · ${data.group}` : ''}`}
        actions={<button className="btn btn-sm" onClick={onVolver}>Todos los recursos</button>} />
      <div className="stack" style={{ gap: 24 }}>
        {data.deleted_at && <Notice tone="warning">Dejó de aparecer en la nube el {dateTime(data.deleted_at)}: su gasto y sus hallazgos se conservan.</Notice>}
        <div className="grid grid-4">
          <StatTile label="Gasto 30 días" value={money(data.cost.total_30d, moneda, 2)} meta={data.cost.by_service[0]?.service ?? 'Sin gasto registrado'} />
          <StatTile label="Hallazgos abiertos" value={number(data.open_findings)} meta={`${number(data.findings.length)} en total`} />
          <StatTile label="Clasificación" value={data.classification?.classification ?? '—'}
            meta={data.classification ? `C${data.classification.confidentiality} · I${data.classification.integrity} · D${data.classification.availability}` : 'Sin clasificar'} />
          <StatTile label="Gobierno" value={data.missing_tags.length ? `Faltan ${data.missing_tags.length} tag${data.missing_tags.length > 1 ? 's' : ''}` : 'Tags completas'}
            meta={data.in_iac === null ? 'Terraform: sin dato' : data.in_iac ? 'En Terraform' : 'Fuera de Terraform'} />
        </div>

        <Section title="Explicación" description="La IA resume qué es, cuánto cuesta, sus riesgos y qué harías, con los datos de esta ficha."
          actions={<button className="btn btn-sm" disabled={pensando} onClick={explicar}><Sparkles size={14} /> {explicacion ? 'Explicar de nuevo' : 'Explicar con IA'}</button>}>
          <Card>{explicacion ? <div className="msg-body"><Markdown text={explicacion} /></div>
            : <Empty>{pensando ? 'Pensando…' : 'Pídele a la IA una explicación del recurso.'}</Empty>}</Card>
        </Section>

        <div className="grid grid-2">
          <Section title="Gasto diario" description="Últimos 90 días con cargos.">
            <Card>{data.cost.daily.length ? <DailyCostChart data={data.cost.daily} currency={moneda} /> : <Empty>Sin gasto registrado para este recurso.</Empty>}</Card>
          </Section>
          <Section title="Gasto por servicio" description="Últimos 30 días.">
            <Card><BarList items={data.cost.by_service.map((s) => ({ key: s.service, cost: s.cost, share: data.cost.total_30d ? (s.cost / data.cost.total_30d) * 100 : 0 }))} currency={moneda} /></Card>
          </Section>
        </div>

        <Section title="Hallazgos" actions={data.findings.length ? <button className="btn btn-ghost btn-sm" onClick={() => onGo('riesgo/hallazgos')}>Gestionarlos</button> : undefined}>
          <Card flush>
            {data.findings.length ? (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Severidad</th><th>Hallazgo</th><th>Estado</th><th>Cómo corregirlo</th></tr></thead>
                  <tbody>
                    {data.findings.map((f) => (
                      <tr key={f.id}>
                        <td><SeverityBadge severity={f.severity} /></td>
                        <td>{f.title}</td>
                        <td className="secondary">{f.status}{f.owner ? ` · ${f.owner}` : ''}{f.accepted_until ? ` · hasta ${f.accepted_until}` : ''}</td>
                        <td className="secondary">{f.remediation ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <Empty>Sin hallazgos.</Empty>}
          </Card>
        </Section>

        {data.cluster && (
          <Section title="Incidentes" actions={<button className="btn btn-ghost btn-sm" onClick={() => onGo(`activos/kubernetes/${data.cluster}`)}>Ver el clúster</button>}>
            <Card flush>
              {data.incidents.length ? (
                <div className="table-wrap">
                  <table className="table">
                    <tbody>
                      {data.incidents.map((i) => (
                        <tr key={i.id}>
                          <td><SeverityBadge severity={i.severity} /></td>
                          <td><button className="btn btn-ghost btn-sm" onClick={() => onGo(`operacion/incidentes/${i.id}`)}>#{i.id} {i.title}</button></td>
                          <td className="secondary">{i.status}</td>
                          <td className="secondary" style={{ whiteSpace: 'nowrap' }}>{dateTime(i.opened_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <Empty>Sin incidentes.</Empty>}
            </Card>
          </Section>
        )}

        <div className="grid grid-2">
          <Section title="Etiquetas">
            <Card>
              {data.missing_tags.length > 0 && <Notice tone="warning">Faltan las tags obligatorias: {data.missing_tags.join(', ')}.</Notice>}
              {Object.keys(data.tags).length ? (
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
                  {Object.entries(data.tags).map(([k, v]) => <Badge key={k}>{k}: {v}</Badge>)}
                </div>
              ) : <Empty>Sin etiquetas.</Empty>}
            </Card>
          </Section>
          <Section title="Línea de tiempo">
            <Card>
              <ol className="timeline">
                {data.timeline.map((e, n) => (
                  <li key={n}>
                    <div><strong>{e.text}</strong></div>
                    <div className="when">{dateTime(e.at)} · {e.actor}</div>
                  </li>
                ))}
              </ol>
            </Card>
          </Section>
        </div>
      </div>
    </>
  );
}

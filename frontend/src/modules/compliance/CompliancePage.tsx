import { useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { get } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, number } from '../../lib/format';
import type { ComplianceControl, ComplianceRule, ComplianceStatus, ControlStatus } from '../../lib/types';
import {
  Card, Drawer, ErrorState, Loading, Notice, PageHeader, Section, Segmented, SeverityBadge, StatTile, Tabs,
} from '../../components/ui';
import { AssetsView } from './AssetsView';
import { ControlRefs, ControlStatusBadge } from './controls';
import { CONTROL_STATUS, SHORT } from './status';

type View = 'controles' | 'reglas' | 'activos';

/**
 * Cumplimiento: qué controles de CIS e ISO 27001 evidencian las reglas de la
 * plataforma, el catálogo de reglas y la clasificación ISO de los activos.
 * Todo sale de la base (recolector diario); nada del Excel del pipeline.
 */
export function CompliancePage({ view, onView, onGo }: {
  view: string | undefined;
  onView: (v: View) => void;
  onGo: (path: string) => void;
}) {
  const active: View = view === 'reglas' || view === 'activos' ? view : 'controles';
  return (
    <>
      <PageHeader
        title="Cumplimiento"
        description="Estado de los controles de CIS Azure Foundations e ISO/IEC 27001:2022 que la plataforma evalúa, el catálogo de reglas que los evidencian y la clasificación de activos de información (ISO 27001 A.5.9 y A.5.12)."
      />
      <Tabs<View>
        value={active}
        onChange={onView}
        tabs={[
          { id: 'controles', label: 'Controles' },
          { id: 'reglas', label: 'Catálogo de reglas' },
          { id: 'activos', label: 'Clasificación de activos' },
        ]}
      />
      {active === 'activos' ? <AssetsView onGo={onGo} /> : <StatusViews view={active} onGo={onGo} />}
    </>
  );
}

function StatusViews({ view, onGo }: { view: 'controles' | 'reglas'; onGo: (path: string) => void }) {
  const { data, error, loading, refreshing, reload } = useApi<ComplianceStatus>('compliance', () => get('/api/compliance'));

  if (loading) return <Loading label="Evaluando los controles…" />;
  if (error && !data) {
    return (
      <div className="stack">
        <Notice tone="warning"><strong>El cumplimiento no está disponible.</strong> {error}. Se calcula desde la base de datos del recolector diario.</Notice>
        <ErrorState error={error} onRetry={reload} />
      </div>
    );
  }
  if (!data) return null;

  return (
    <div className="stack" style={{ gap: 24 }}>
      {view === 'controles' ? <ControlsView data={data} refreshing={refreshing} onGo={onGo} /> : <RulesView data={data} refreshing={refreshing} onGo={onGo} />}
      <div className="muted" style={{ fontSize: 12.5 }}>
        {data.evaluated_at ? <>Evaluado con la recolección del {dateTime(data.evaluated_at)}</> : 'El recolector todavía no evaluó las reglas'}
        {' '}· * evidencia parcial: la regla comprueba una parte de lo que pide el control.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- controles

function ControlsView({ data, refreshing, onGo }: { data: ComplianceStatus; refreshing: boolean; onGo: (path: string) => void }) {
  const [frameworkId, setFrameworkId] = useState(data.frameworks[0]?.id ?? '');
  const [filter, setFilter] = useState<'todos' | ControlStatus>('todos');
  const [selected, setSelected] = useState<ComplianceControl | null>(null);
  const fw = data.frameworks.find((f) => f.id === frameworkId) ?? data.frameworks[0];
  if (!fw) return null;
  const controls = fw.controls.filter((c) => filter === 'todos' || c.status === filter);
  const rules = Object.fromEntries(data.rules.map((r) => [r.id, r]));

  return (
    <>
      {data.failed_rules.length > 0 && (
        <Notice tone="warning">
          {data.failed_rules.length === 1 ? 'Una regla no se pudo evaluar' : `${data.failed_rules.length} reglas no se pudieron evaluar`} en la última recolección; sus controles quedan como <strong>sin evidencia</strong> en vez de darse por cumplidos.
        </Notice>
      )}

      <div className="toolbar">
        <Segmented label="Marco" value={fw.id} onChange={(v) => { setFrameworkId(v); setFilter('todos'); }}
          options={data.frameworks.map((f) => ({ id: f.id, label: SHORT[f.id] === 'CIS' ? `CIS Azure ${f.version}` : 'ISO 27001:2022' }))} />
      </div>

      <div className="grid grid-4">
        {(['no_cumple', 'riesgo_aceptado', 'sin_evidencia', 'cumple'] as ControlStatus[]).map((s) => (
          <StatTile key={s} refreshing={refreshing}
            icon={CONTROL_STATUS[s].dot ? <span className={`dot ${CONTROL_STATUS[s].dot}`} /> : undefined}
            label={CONTROL_STATUS[s].label} value={number(fw.summary[s] ?? 0)} unit={`de ${fw.controls_evaluated}`}
            meta={CONTROL_STATUS[s].hint} />
        ))}
      </div>

      <Section
        title={`${fw.name} ${SHORT[fw.id] === 'CIS' ? fw.version : ''}`.trim()}
        description={`La plataforma evalúa ${fw.controls_evaluated} controles de este marco. No es un puntaje de certificación: los controles que ninguna regla evidencia no se listan ni cuentan.`}
        actions={
          <Segmented label="Estado" value={filter} onChange={setFilter} options={[
            { id: 'todos', label: 'Todos' },
            { id: 'no_cumple', label: `No cumple (${fw.summary.no_cumple ?? 0})` },
            { id: 'sin_evidencia', label: 'Sin evidencia' },
            { id: 'cumple', label: 'Cumple' },
          ]} />
        }
      >
        <Card flush refreshing={refreshing}>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th style={{ width: 90 }}>Control</th><th>Descripción</th><th>Estado</th><th>Evidencia</th><th className="num">Activos</th><th /></tr>
              </thead>
              <tbody>
                {controls.map((c) => (
                  <tr key={c.id}>
                    <td className="mono primary-cell">{c.id}</td>
                    <td><span className="primary-cell">{c.title}</span></td>
                    <td><ControlStatusBadge status={c.status} /></td>
                    <td className="secondary">
                      {c.evidence.length === 1 ? (c.evidence[0].kind === 'rule' ? '1 regla' : 'Clasificación de activos') : `${c.evidence.length} reglas`}
                      {!c.direct && <span className="sub">solo parcial</span>}
                    </td>
                    <td className="num">{c.active ? number(c.active) : <span className="muted">0</span>}</td>
                    <td><div className="row-actions"><button className="btn btn-sm" onClick={() => setSelected(c)}>Detalle</button></div></td>
                  </tr>
                ))}
                {controls.length === 0 && <tr><td colSpan={6} className="table-empty">Ningún control en este estado.</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>
      </Section>

      {selected && (
        <Drawer
          title={`${SHORT[fw.id] ?? ''} ${selected.id}`}
          subtitle={<ControlStatusBadge status={selected.status} />}
          onClose={() => setSelected(null)}
          footer={selected.active > 0 && selected.evidence.some((e) => e.kind === 'rule')
            ? <button className="btn btn-primary" onClick={() => onGo('secops/gestion')}>Ir a la gestión de hallazgos</button>
            : selected.evidence.some((e) => e.kind === 'classification')
              ? <button className="btn btn-primary" onClick={() => onGo('cumplimiento/activos')}>Ver la clasificación de activos</button>
              : undefined}
        >
          <p style={{ margin: 0, fontSize: 13.5 }}><strong>{selected.title}</strong></p>
          <p className="secondary" style={{ margin: 0, fontSize: 13 }}>{CONTROL_STATUS[selected.status].hint}. El estado es el peor de su evidencia.</p>
          <div className="subhead">Evidencia</div>
          <div className="stack" style={{ gap: 12 }}>
            {selected.evidence.map((e, i) => {
              const r = e.rule_id ? rules[e.rule_id] : undefined;
              return (
                <Card key={i}>
                  <div className="spread" style={{ gap: 8 }}>
                    <strong style={{ fontSize: 13 }}>{e.title}</strong>
                    <ControlStatusBadge status={e.status} />
                  </div>
                  <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                    {e.kind === 'rule' ? <span className="mono">{e.rule_id}</span> : 'Clasificación de activos'} · evidencia {e.match}
                    {e.kind === 'rule' && <> · {number(e.active)} activo(s){e.accepted ? `, ${number(e.accepted)} aceptado(s)` : ''}</>}
                    {e.kind === 'classification' && e.active > 0 && <> · {number(e.active)} pendiente(s)</>}
                  </div>
                  {r && <p className="secondary" style={{ margin: '8px 0 0', fontSize: 13 }}>{r.description}</p>}
                  {r && <p style={{ margin: '6px 0 0', fontSize: 13 }}><strong>Cómo corregirlo:</strong> {r.remediation}</p>}
                </Card>
              );
            })}
          </div>
        </Drawer>
      )}
    </>
  );
}

// ---------------------------------------------------------------- reglas

function RulesView({ data, refreshing, onGo }: { data: ComplianceStatus; refreshing: boolean; onGo: (path: string) => void }) {
  const [selected, setSelected] = useState<ComplianceRule | null>(null);
  const activas = data.rules.reduce((n, r) => n + r.active, 0);

  return (
    <>
      <div className="grid grid-4">
        <StatTile refreshing={refreshing} label="Reglas en el catálogo" value={number(data.rules.length)} meta="Detectivas, evaluadas cada día" />
        <StatTile refreshing={refreshing} icon={<span className="dot dot-critical" />} label="Con hallazgos activos" value={number(data.rules.filter((r) => r.active > 0).length)} meta={`${number(activas)} hallazgo(s) abiertos o asumidos`} />
        <StatTile refreshing={refreshing} label="Sin evaluar" value={number(data.rules.filter((r) => !r.evaluated).length)} meta="Consulta fallida o sin recolección" />
        <StatTile refreshing={refreshing} icon={<span className="dot dot-good" />} label="Hallazgos resueltos" value={number(data.rules.reduce((n, r) => n + r.resolved, 0))} meta="Corregidos y confirmados por el recolector" />
      </div>

      <Section title="Reglas" description="Cada regla tiene un identificador estable, la severidad por defecto (el recolector la sube según la exposición real) y los controles que evidencia.">
        <Card flush refreshing={refreshing}>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Severidad</th><th>Regla</th><th>Controles</th><th>Estado</th><th className="num">Activos</th><th /></tr>
              </thead>
              <tbody>
                {data.rules.map((r) => (
                  <tr key={r.id}>
                    <td style={{ width: 110 }}><SeverityBadge severity={r.severity_default} /></td>
                    <td><span className="primary-cell">{r.title}</span><span className="sub mono">{r.id}</span></td>
                    <td><ControlRefs frameworks={r.frameworks} /></td>
                    <td><ControlStatusBadge status={r.status} /></td>
                    <td className="num">{r.active ? number(r.active) : <span className="muted">0</span>}</td>
                    <td><div className="row-actions"><button className="btn btn-sm" onClick={() => setSelected(r)}>Detalle</button></div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </Section>

      {selected && (
        <Drawer
          title={selected.title}
          subtitle={<><SeverityBadge severity={selected.severity_default} /> <ControlStatusBadge status={selected.status} /></>}
          onClose={() => setSelected(null)}
          footer={selected.active > 0 ? <button className="btn btn-primary" onClick={() => onGo('secops/gestion')}>Ver sus hallazgos</button> : undefined}
        >
          <dl className="kv">
            <dt>Identificador</dt><dd className="mono">{selected.id}</dd>
            <dt>Hallazgos</dt>
            <dd>{number(selected.active)} activo(s) · {number(selected.accepted)} aceptado(s) · {number(selected.resolved)} resuelto(s)</dd>
            <dt>Evaluada</dt><dd>{selected.evaluated ? 'Sí, en la última recolección' : 'No: su consulta falló o el recolector no ha corrido'}</dd>
          </dl>
          <div>
            <div className="subhead">Qué riesgo representa</div>
            <p style={{ margin: '6px 0 0', fontSize: 13 }}>{selected.description}</p>
          </div>
          <div>
            <div className="subhead">Cómo se detecta</div>
            <p style={{ margin: '6px 0 0', fontSize: 13 }}>{selected.detection}</p>
          </div>
          <div>
            <div className="subhead">Cómo corregirlo</div>
            <p style={{ margin: '6px 0 0', fontSize: 13 }}>{selected.remediation}</p>
          </div>
          <div>
            <div className="subhead" style={{ marginBottom: 6 }}>Controles que evidencia</div>
            <table className="table">
              <thead><tr><th>Marco</th><th>Control</th><th>Evidencia</th></tr></thead>
              <tbody>
                {Object.entries(selected.frameworks).flatMap(([m, cs]) => cs.map((c) => {
                  const fw = data.frameworks.find((f) => f.id === m);
                  const ctl = fw?.controls.find((x) => x.id === c.control);
                  return (
                    <tr key={`${m}-${c.control}`}>
                      <td>{SHORT[m] ?? m}</td>
                      <td><span className="mono primary-cell">{c.control}</span>{ctl && <span className="sub">{ctl.title}</span>}</td>
                      <td>{c.match === 'directa' ? 'Directa' : 'Parcial'}</td>
                    </tr>
                  );
                }))}
              </tbody>
            </table>
          </div>
          {selected.references.length > 0 && (
            <div>
              <div className="subhead">Referencias</div>
              <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 13 }}>
                {selected.references.map((u) => (
                  <li key={u}><a href={u} target="_blank" rel="noreferrer">{u.replace('https://', '')} <ExternalLink size={12} /></a></li>
                ))}
              </ul>
            </div>
          )}
        </Drawer>
      )}
    </>
  );
}

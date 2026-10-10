import { useState } from 'react';
import { Download, Search } from 'lucide-react';
import { download, get, post } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, number, shortType } from '../../lib/format';
import type { AssetClass, ClassifiedAsset, ClassifiedAssets } from '../../lib/types';
import { useApp } from '../../state/hooks';
import {
  Card, Drawer, Empty, ErrorState, Loading, Notice, Pagination, Section, Segmented, StatTile,
} from '../../components/ui';

const CLASSES: AssetClass[] = ['Confidencial', 'Restringido', 'Uso interno'];
const CLASS_DOT: Record<AssetClass, string> = {
  Confidencial: 'dot-critical',
  Restringido: 'dot-serious',
  'Uso interno': 'dot-accent',
};
/** Valores de partida al elegir una clasificación a mano; se pueden ajustar. */
const CLASS_CID: Record<AssetClass, [number, number, number]> = {
  Confidencial: [3, 3, 3],
  Restringido: [2, 2, 2],
  'Uso interno': [1, 1, 1],
};
const PAGE = 50;

function ClassBadge({ value, manual }: { value: AssetClass | null; manual?: boolean }) {
  if (!value) return <span className="muted">Sin clasificar</span>;
  return (
    <span className="badge" title={manual ? 'Clasificación fijada a mano' : 'Clasificación automática'}>
      <span className={`dot ${CLASS_DOT[value]}`} aria-hidden="true" />
      {value}{manual ? ' · manual' : ''}
    </span>
  );
}

/**
 * Clasificación ISO 27001 de activos (A.5.9 inventario, A.5.12 clasificación).
 *
 * La calcula el recolector cada día con una regla explicable (ambiente y tipo
 * de recurso). Un operador puede fijarla a mano con un motivo; el recolector la
 * respeta hasta que se restaure la automática. Cada cambio queda auditado.
 */
export function AssetsView({ onGo }: { onGo: (path: string) => void }) {
  const { data, error, loading, refreshing, reload } = useApi<ClassifiedAssets>('compliance-assets', () => get('/api/compliance/assets'));
  const { toast } = useApp();
  const [filter, setFilter] = useState<'todos' | AssetClass | 'riesgo' | 'sin_custodio'>('todos');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<ClassifiedAsset | null>(null);
  const [exporting, setExporting] = useState(false);

  if (loading) return <Loading label="Leyendo la clasificación…" />;
  if (error && !data) {
    return (
      <div className="stack">
        <Notice tone="warning"><strong>La clasificación no está disponible.</strong> {error}.</Notice>
        <ErrorState error={error} onRetry={reload} />
      </div>
    );
  }
  if (!data) return null;
  if (!data.items.length) {
    return <Card><Empty title="Sin activos todavía">El recolector diario carga el inventario y lo clasifica. Vuelve después de la próxima recolección.</Empty></Card>;
  }

  const st = data.stats;
  const q = query.trim().toLowerCase();
  const items = data.items.filter((a) =>
    (filter === 'todos' || (filter === 'riesgo' ? a.risk_required : filter === 'sin_custodio' ? !a.custodian : a.classification === filter))
    && (!q || [a.name, a.type, a.group, a.custodian, a.account].some((v) => v?.toLowerCase().includes(q))));
  const visible = items.slice((page - 1) * PAGE, page * PAGE);

  async function exportar() {
    setExporting(true);
    try {
      await download('/api/compliance/assets/export', undefined, 'activos-clasificados.csv');
    } catch (e) {
      toast(`No se pudo exportar: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="stack" style={{ gap: 24 }}>
      <div className="grid grid-4">
        <StatTile refreshing={refreshing} label="Activos clasificados" value={number(st.classified)} unit={`de ${number(st.total)}`}
          meta={st.manual ? `${number(st.manual)} fijado(s) a mano` : 'Todos con la regla automática'} />
        <StatTile refreshing={refreshing} icon={<span className="dot dot-critical" />} label="Confidenciales" value={number(st.by_class.Confidencial ?? 0)}
          meta={`${number(st.by_class.Restringido ?? 0)} restringidos · ${number(st.by_class['Uso interno'] ?? 0)} de uso interno`} />
        <StatTile refreshing={refreshing} label="Requieren análisis de riesgo" value={number(st.risk_required)} meta={`Criticidad promedio ${number(st.average_score, 1)} de 9`} />
        <StatTile refreshing={refreshing} label="Sin custodio" value={number(st.without_custodian)} meta="Ni tag de propietario ni creador conocido" />
      </div>

      <Section
        title="Activos"
        description="Confidencialidad, integridad y disponibilidad de 1 a 3; la criticidad es su suma. La regla automática decide por ambiente (tag Environment) y por si el recurso guarda datos o llaves."
        actions={<button className="btn btn-sm" onClick={exportar} disabled={exporting}><Download size={14} /> {exporting ? 'Exportando…' : 'Exportar CSV'}</button>}
      >
        <div className="toolbar" style={{ marginBottom: 12 }}>
          <div className="input-icon grow">
            <Search size={14} />
            <input className="input" placeholder="Buscar por nombre, tipo, grupo o custodio" value={query}
              onChange={(e) => { setQuery(e.target.value); setPage(1); }} />
          </div>
          <Segmented label="Filtro" value={filter} onChange={(v) => { setFilter(v); setPage(1); }} options={[
            { id: 'todos', label: 'Todos' },
            ...CLASSES.filter((c) => st.by_class[c]).map((c) => ({ id: c, label: c })),
            { id: 'riesgo', label: 'Análisis de riesgo' },
            { id: 'sin_custodio', label: 'Sin custodio' },
          ]} />
        </div>
        <Card flush refreshing={refreshing}>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Activo</th><th>Clasificación</th><th>Custodio</th><th className="center">C · I · D</th><th className="num">Criticidad</th><th>Análisis de riesgo</th><th className="num">Hallazgos</th><th /></tr>
              </thead>
              <tbody>
                {visible.map((a) => (
                  <tr key={a.uid}>
                    <td>
                      <span className="primary-cell">{a.name}</span>
                      <span className="sub">{[shortType(a.type), a.environment, a.group].filter(Boolean).join(' · ')}</span>
                    </td>
                    <td><ClassBadge value={a.classification} manual={a.method === 'manual'} /></td>
                    <td className="secondary">{a.custodian || <span className="muted">—</span>}</td>
                    <td className="center mono">{a.classification ? `${a.confidentiality} · ${a.integrity} · ${a.availability}` : '—'}</td>
                    <td className="num primary-cell">{a.score ?? '—'}</td>
                    <td>{a.risk_required ? <span className="badge"><span className="dot dot-serious" />Requerido</span> : <span className="muted">No</span>}</td>
                    <td className="num">{a.open_findings ? number(a.open_findings) : <span className="muted">0</span>}</td>
                    <td><div className="row-actions"><button className="btn btn-sm" onClick={() => setSelected(a)}>Detalle</button></div></td>
                  </tr>
                ))}
                {visible.length === 0 && <tr><td colSpan={8} className="table-empty">Ningún activo coincide.</td></tr>}
              </tbody>
            </table>
          </div>
          {items.length > PAGE && <Pagination page={page} pageSize={PAGE} total={items.length} onPage={setPage} />}
        </Card>
      </Section>

      <div className="muted" style={{ fontSize: 12.5 }}>
        {data.collected_at ? <>Clasificación del {dateTime(data.collected_at)}</> : 'El recolector todavía no clasificó el inventario'}
        {' '}· Las clasificaciones manuales se mantienen en cada recolección.
      </div>

      {selected && (
        <AssetDrawer
          asset={selected}
          onClose={() => setSelected(null)}
          onChanged={(a) => { setSelected(a); reload(); }}
          onGo={onGo}
        />
      )}
    </div>
  );
}

function AssetDrawer({ asset: a, onClose, onChanged, onGo }: {
  asset: ClassifiedAsset;
  onClose: () => void;
  onChanged: (a: ClassifiedAsset) => void;
  onGo: (path: string) => void;
}) {
  const { toast, can } = useApp();
  const puedeEditar = can('operador');
  const [editing, setEditing] = useState(false);
  const [cls, setCls] = useState<AssetClass>(a.classification ?? 'Restringido');
  const [cid, setCid] = useState<[number, number, number]>([a.confidentiality ?? 2, a.integrity ?? 2, a.availability ?? 2]);
  const [risk, setRisk] = useState(a.risk_required ?? false);
  const [custodian, setCustodian] = useState(a.custodian ?? '');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function enviar(restaurar: boolean) {
    setBusy(true);
    setError(null);
    try {
      const r = restaurar
        ? await post<ClassifiedAsset>('/api/compliance/assets/classification/restore', { resource_uid: a.uid })
        : await post<ClassifiedAsset>('/api/compliance/assets/classification', {
          resource_uid: a.uid, classification: cls, confidentiality: cid[0], integrity: cid[1], availability: cid[2],
          risk_required: risk, reason: reason.trim(), custodian: custodian.trim() || null,
        });
      toast(restaurar ? 'Clasificación automática restaurada.' : `Clasificado como ${r.classification}.`);
      setEditing(false);
      setReason('');
      onChanged(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const nivel = (i: 0 | 1 | 2, etiqueta: string) => (
    <label className="field">
      {etiqueta}
      <select className="select" value={cid[i]} onChange={(e) => {
        const n = [...cid] as [number, number, number];
        n[i] = Number(e.target.value);
        setCid(n);
      }}>
        <option value={1}>1 · Bajo</option>
        <option value={2}>2 · Medio</option>
        <option value={3}>3 · Alto</option>
      </select>
    </label>
  );

  return (
    <Drawer
      title={a.name}
      subtitle={<ClassBadge value={a.classification} manual={a.method === 'manual'} />}
      onClose={onClose}
      footer={editing ? (
        <>
          <button className="btn" onClick={() => setEditing(false)} disabled={busy}>Cancelar</button>
          <button className="btn btn-primary" onClick={() => enviar(false)} disabled={busy || !reason.trim()}>
            {busy ? 'Guardando…' : 'Guardar clasificación'}
          </button>
        </>
      ) : (
        <>
          {a.open_findings > 0 && <button className="btn btn-ghost" onClick={() => onGo('secops/gestion')}>Ver sus hallazgos</button>}
          {puedeEditar && a.method === 'manual' && (
            <button className="btn" onClick={() => enviar(true)} disabled={busy}>Restaurar la automática</button>
          )}
          {puedeEditar && <button className="btn btn-primary" onClick={() => setEditing(true)}>Cambiar clasificación</button>}
        </>
      )}
    >
      <dl className="kv">
        <dt>Tipo</dt><dd>{shortType(a.type)}</dd>
        {a.group && <><dt>Grupo</dt><dd>{a.group}</dd></>}
        {a.account && <><dt>Suscripción</dt><dd>{a.account}</dd></>}
        <dt>Ambiente</dt><dd>{a.environment ?? <span className="muted">Sin tag Environment</span>}</dd>
        <dt>Custodio</dt><dd>{a.custodian ?? <span className="muted">Sin custodio</span>}</dd>
        {a.classification && (
          <>
            <dt>C · I · D</dt><dd className="mono">{a.confidentiality} · {a.integrity} · {a.availability} (criticidad {a.score} de 9)</dd>
            <dt>Análisis de riesgo</dt><dd>{a.risk_required ? 'Requerido' : 'No requerido'}</dd>
            <dt>Método</dt><dd>{a.method === 'manual' ? 'Manual' : 'Automático'}</dd>
            <dt>Motivo</dt><dd>{a.reason ?? '—'}</dd>
            {a.updated_at && <><dt>Actualizado</dt><dd>{dateTime(a.updated_at)} · {a.updated_by}</dd></>}
          </>
        )}
        <dt>Hallazgos activos</dt><dd>{number(a.open_findings)}</dd>
      </dl>

      {!puedeEditar && <Notice>Cambiar la clasificación requiere el rol Operador.</Notice>}

      {editing && (
        <div className="stack" style={{ gap: 12 }}>
          <div className="subhead">Clasificación manual</div>
          <Notice>El recolector mantendrá esta clasificación hasta que alguien restaure la automática. El cambio queda en la auditoría.</Notice>
          <label className="field">
            Clasificación
            <select className="select" value={cls} onChange={(e) => {
              const c = e.target.value as AssetClass;
              setCls(c);
              setCid(CLASS_CID[c]);
              setRisk(c === 'Confidencial' || risk);
            }}>
              {CLASSES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <div className="grid grid-3" style={{ gap: 10 }}>
            {nivel(0, 'Confidencialidad')}
            {nivel(1, 'Integridad')}
            {nivel(2, 'Disponibilidad')}
          </div>
          <label className="check">
            <input type="checkbox" checked={risk} onChange={(e) => setRisk(e.target.checked)} />
            Requiere análisis de riesgo
          </label>
          <label className="field">
            Custodio
            <input className="input" value={custodian} onChange={(e) => setCustodian(e.target.value)} maxLength={320}
              placeholder="Persona o equipo responsable" />
          </label>
          <label className="field">
            Motivo (obligatorio)
            <textarea className="input textarea" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000}
              placeholder="Por qué difiere de la regla automática" />
          </label>
          {error && <Notice tone="critical">{error}</Notice>}
        </div>
      )}
      {!editing && error && <Notice tone="critical">{error}</Notice>}
    </Drawer>
  );
}

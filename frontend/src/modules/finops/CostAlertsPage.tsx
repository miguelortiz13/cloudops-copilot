import { useState } from 'react';
import { Sparkles } from 'lucide-react';
import { get, post } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, money } from '../../lib/format';
import { Markdown } from '../../lib/markdown';
import { useApp } from '../../state/hooks';
import { Card, Drawer, Empty, ErrorState, Loading, Notice, PageHeader, Segmented } from '../../components/ui';

interface Alerta {
  id: number; kind: 'anomalia' | 'presupuesto' | 'export_vacio'; provider: string; account: string | null; day: string | null;
  amount: number; reference: number | null; title: string; status: 'abierto' | 'reconocido' | 'resuelto' | 'descartado';
  assignee: string | null; note: string | null; explanation: string | null; opened_at: string; updated_by: string | null;
}

const TIPO = { anomalia: 'Gasto anómalo', presupuesto: 'Presupuesto', export_vacio: 'Export sin filas' } as const;
const ESTADO = {
  abierto: { label: 'Abierta', dot: 'dot-critical' }, reconocido: { label: 'Reconocida', dot: 'dot-warning' },
  resuelto: { label: 'Resuelta', dot: 'dot-good' }, descartado: { label: 'Descartada', dot: 'dot-good' },
} as const;

function cifra(a: Alerta): string {
  if (a.kind === 'export_vacio') return 'Sin filas';
  const ref = a.reference === null ? '' : a.kind === 'anomalia' ? ` (media ${money(a.reference, 'USD', 2)})` : ` de ${money(a.reference, 'USD', 2)}`;
  return `${money(a.amount, 'USD', 2)}${ref}`;
}

/** Costos → Alertas: anomalías de gasto, presupuestos y exports vacíos, con su gestión y la explicación de la IA. */
export function CostAlertsPage() {
  const [filtro, setFiltro] = useState<'vivos' | ''>('vivos');
  const [elegida, setElegida] = useState<Alerta | null>(null);
  const { data, error, loading, refreshing, reload } = useApi<{ items: Alerta[]; open: number }>(
    `costos-alertas-${filtro}`, () => get(`/api/costos/alertas${filtro ? '?estado=vivos' : ''}`));
  if (loading && !data) return <Loading label="Consultando la base (puede tardar un minuto si estaba pausada)…" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  const items = data?.items ?? [];

  return (
    <>
      <PageHeader title="Alertas de costo" description="Cada gasto diario anómalo, presupuesto al 80 % o 100 % (o con pronóstico de superarse) y export de costos que no devuelve filas queda aquí para reconocerlo, explicarlo y cerrarlo." />
      <div className="toolbar" style={{ marginBottom: 12 }}>
        <Segmented label="Estado" value={filtro} onChange={setFiltro} options={[{ id: 'vivos', label: `Abiertas (${data?.open ?? 0})` }, { id: '', label: 'Últimos 90 días' }]} />
      </div>
      <Card flush refreshing={refreshing}>
        {items.length ? (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Alerta</th><th>Tipo</th><th>Cifra</th><th>Estado</th><th>Abierta</th></tr></thead>
              <tbody>
                {items.map((a) => (
                  <tr key={a.id}>
                    <td><button className="btn btn-ghost btn-sm" onClick={() => setElegida(a)}>{a.title}</button></td>
                    <td className="secondary">{TIPO[a.kind]} · {a.provider.toUpperCase()}</td>
                    <td className="num">{cifra(a)}</td>
                    <td><span className="badge"><span className={`dot ${ESTADO[a.status].dot}`} aria-hidden="true" />{ESTADO[a.status].label}{a.assignee ? ` · ${a.assignee}` : ''}</span></td>
                    <td className="secondary" style={{ whiteSpace: 'nowrap' }}>{dateTime(a.opened_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty title={filtro ? 'Sin alertas abiertas' : 'Sin alertas en 90 días'}>Las registra el job diario cuando detecta una anomalía o un presupuesto en riesgo.</Empty>}
      </Card>
      {elegida && <Detalle a={elegida} onClose={() => setElegida(null)} onCambio={() => { setElegida(null); reload(); }} />}
    </>
  );
}

function Detalle({ a, onClose, onCambio }: { a: Alerta; onClose: () => void; onCambio: () => void }) {
  const { can, toast } = useApp();
  const [nota, setNota] = useState(a.note ?? '');
  const [explicacion, setExplicacion] = useState(a.explanation);
  const [enviando, setEnviando] = useState(false);
  const operador = can('operador');
  const vivo = a.status === 'abierto' || a.status === 'reconocido';

  const cambiar = async (status: Alerta['status']) => {
    setEnviando(true);
    try {
      await post(`/api/costos/alertas/${a.id}`, { status, note: nota });
      toast(`Alerta ${ESTADO[status].label.toLowerCase()}`);
      onCambio();
    } catch (e) {
      toast(`No se pudo: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setEnviando(false);
    }
  };
  const explicar = async () => {
    setEnviando(true);
    try {
      setExplicacion((await post<{ explanation: string }>(`/api/costos/alertas/${a.id}/explicacion`, {})).explanation);
    } catch (e) {
      toast(`No se pudo explicar: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setEnviando(false);
    }
  };

  return (
    <Drawer title={a.title} subtitle={`${TIPO[a.kind]} · ${cifra(a)}${a.account ? ` · ${a.account}` : ''}`} onClose={onClose}
      footer={operador ? (
        <div className="row-actions">
          {vivo && a.status === 'abierto' && <button className="btn btn-sm" disabled={enviando} onClick={() => cambiar('reconocido')}>Reconocer</button>}
          {vivo && <button className="btn btn-sm" disabled={enviando} onClick={() => cambiar('descartado')}>Descartar</button>}
          {vivo && <button className="btn btn-primary btn-sm" disabled={enviando} onClick={() => cambiar('resuelto')}>Resolver</button>}
          {!vivo && <button className="btn btn-sm" disabled={enviando} onClick={() => cambiar('abierto')}>Reabrir</button>}
        </div>
      ) : undefined}>
      <div className="stack" style={{ gap: 16 }}>
        {a.kind === 'export_vacio' && <Notice tone="warning">El export entrega archivos pero la consulta no devuelve filas: revisa la tabla de Athena (ubicación, particiones) antes de confiar en el gasto de AWS.</Notice>}
        <div>
          <div className="row-actions" style={{ justifyContent: 'space-between' }}>
            <div className="subhead">Explicación</div>
            <button className="btn btn-sm" disabled={enviando} onClick={explicar}><Sparkles size={14} /> {explicacion ? 'Explicar de nuevo' : 'Explicar con IA'}</button>
          </div>
          {explicacion ? <div className="msg-body" style={{ marginTop: 8 }}><Markdown text={explicacion} /></div>
            : <p className="secondary" style={{ fontSize: 13 }}>La IA compara el día con la media de los anteriores por servicio y por recurso, y cruza los recursos nuevos de esos días.</p>}
        </div>
        {operador && (
          <label className="field">
            Nota
            <textarea className="input textarea" value={nota} maxLength={2000} onChange={(e) => setNota(e.target.value)} placeholder="Qué fue y qué se hizo" />
          </label>
        )}
        {!operador && a.note && <p style={{ fontSize: 13 }}><strong>Nota:</strong> {a.note}</p>}
        {a.updated_by && <p className="secondary" style={{ fontSize: 12 }}>Última gestión: {a.updated_by}</p>}
      </div>
    </Drawer>
  );
}

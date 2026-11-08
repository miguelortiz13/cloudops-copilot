import { useState } from 'react';
import { get } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, number } from '../../lib/format';
import { Card, Empty, ErrorState, Loading, Notice, PageHeader, Segmented, StatTile } from '../../components/ui';

interface Aviso {
  at: string; dominio: string; tipo: string; severidad: string; clave: string; titulo: string; enlace: string | null;
  canal: string | null; modo: 'registro' | 'activo'; decision: 'enviado' | 'silenciado' | 'duplicado';
  silencio: string | null; enviado: boolean; error: string | null;
}
interface Registro { mode: 'registro' | 'activo'; items: Aviso[]; stats: { total: number; enviados: number; silenciados: number; duplicados: number; fallidos: number } }

const DOMINIO: Record<string, string> = {
  inicio: 'Inicio', activos: 'Activos', costos: 'Costos', riesgo: 'Riesgo', operacion: 'Operación', plataforma: 'Plataforma',
};
const TIPO: Record<string, string> = {
  atencion_diaria: 'Requiere atención (diario)', kubernetes: 'Kubernetes', incidente: 'Incidente',
  incidente_resuelto: 'Incidente resuelto', reporte_mensual: 'Reporte mensual', resumen_semanal: 'Resumen semanal',
};

function Decision({ a }: { a: Aviso }) {
  if (a.error) return <span className="badge"><span className="dot dot-critical" aria-hidden="true" />Falló: {a.error}</span>;
  if (a.decision === 'enviado') return <span className="badge"><span className="dot dot-good" aria-hidden="true" />Enviado</span>;
  const que = a.decision === 'silenciado' ? 'silenciado' : 'descartado por duplicado';
  return (
    <span className="badge"><span className="dot dot-warning" aria-hidden="true" />
      {a.enviado ? `Enviado; en modo activo habría sido ${que}` : a.decision === 'silenciado' ? 'Silenciado' : 'Duplicado, no enviado'}
    </span>
  );
}

/** Operación → Avisos: todo lo que la plataforma publicó en el canal y qué decidió el motor de avisos. */
export function NotificationsPage() {
  const [dias, setDias] = useState<'1' | '7' | '30'>('7');
  const { data, error, loading, refreshing, reload } = useApi<Registro>(`notifications-${dias}`, () => get(`/api/notifications?dias=${dias}`));
  if (loading) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  const s = data.stats;

  return (
    <>
      <PageHeader title="Avisos" description="Todo lo que la plataforma publicó en el canal de avisos (Discord, Slack o Teams): de qué dominio, qué decidió el motor y si llegó." />
      <div className="stack" style={{ gap: 24 }}>
        {data.mode === 'registro' && (
          <Notice>
            El motor está en <strong>modo registro</strong>: envía todo como antes y anota lo que habría silenciado o descartado por duplicado.
            Cuando esas decisiones se vean bien, pásalo a activo en <em>Plataforma → Ajustes → Avisos</em>.
          </Notice>
        )}
        <div className="grid grid-4">
          <StatTile refreshing={refreshing} label="Avisos" value={number(s.total)} meta={`En ${dias === '1' ? 'el último día' : `${dias} días`}`} />
          <StatTile refreshing={refreshing} label="Enviados" value={number(s.enviados)} />
          <StatTile refreshing={refreshing} label="Silenciados o duplicados" value={number(s.silenciados + s.duplicados)}
            meta={data.mode === 'registro' ? 'Habrían sido, en modo activo' : undefined} />
          <StatTile refreshing={refreshing} label="Fallidos" value={number(s.fallidos)} meta="El canal no respondió" />
        </div>
        <div className="toolbar">
          <Segmented label="Periodo" value={dias} onChange={setDias} options={[{ id: '1', label: '24 horas' }, { id: '7', label: '7 días' }, { id: '30', label: '30 días' }]} />
        </div>
        {data.items.length === 0 ? <Card><Empty title="Sin avisos en este periodo">El registro empieza con el motor de avisos (fase 2 del plan).</Empty></Card> : (
          <Card flush refreshing={refreshing}>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Cuándo</th><th>Dominio</th><th>Aviso</th><th>Severidad</th><th>Resultado</th></tr></thead>
                <tbody>
                  {data.items.map((a, n) => (
                    <tr key={`${a.at}-${n}`}>
                      <td className="secondary" style={{ whiteSpace: 'nowrap' }}>{dateTime(a.at)}</td>
                      <td className="secondary">{DOMINIO[a.dominio] ?? a.dominio}</td>
                      <td>
                        <div>{a.enlace ? <a href={a.enlace.slice(a.enlace.indexOf('#'))}>{a.titulo}</a> : a.titulo}</div>
                        <div className="secondary" style={{ fontSize: 12 }}>{TIPO[a.tipo] ?? a.tipo}{a.canal ? ` · ${a.canal}` : ''}</div>
                      </td>
                      <td className="secondary">{a.severidad}</td>
                      <td><Decision a={a} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </div>
    </>
  );
}

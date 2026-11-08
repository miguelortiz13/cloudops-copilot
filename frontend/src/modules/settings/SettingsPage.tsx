import { useState } from 'react';
import { get, post, put } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime } from '../../lib/format';
import { useApp } from '../../state/hooks';
import { Badge, Card, Empty, ErrorState, Loading, Notice, PageHeader, Section } from '../../components/ui';
import { IncidentSettingsView } from '../incidents/IncidentSettingsView';
import { ChecksStatus } from './ChecksStatus';

type Valor = number | boolean | string[];
interface SeccionApi { values: Record<string, Valor>; defaults: Record<string, Valor>; origin: 'ajuste' | 'variable' | 'defecto'; schema: Record<string, (string | number | boolean)[]> }
interface Cambio { at: string; actor: string; seccion: string; antes: Record<string, unknown>; despues: Record<string, unknown> }

const ORIGEN = {
  ajuste: 'Guardado en el panel',
  variable: 'Valor inicial de la variable de entorno: se guarda aquí al cambiarlo',
  defecto: 'Valor por defecto',
} as const;

/** Las secciones genéricas: cada campo es una lista de nombres (separados por comas) o un número. */
const SECCIONES: { id: string; titulo: string; descripcion: string; campos: { k: string; label: string; hint: string }[] }[] = [
  {
    id: 'gobierno', titulo: 'Gobierno', descripcion: 'Las etiquetas que la plataforma exige y con las que reparte el gasto. Se aplican desde la próxima recolección.',
    campos: [
      { k: 'tags_obligatorias', label: 'Tags obligatorias', hint: 'Separadas por comas. Un recurso sin alguna de ellas incumple la gobernanza.' },
      { k: 'tags_showback', label: 'Tags de reparto del gasto (showback)', hint: 'Separadas por comas. Con ellas se agrupa el gasto en Costos.' },
    ],
  },
  {
    id: 'costos', titulo: 'Costos', descripcion: 'Presupuesto mensual por nube. Se avisa al 80 % y al 100 %, y sale en el reporte mensual.',
    campos: [
      { k: 'presupuesto_azure_usd', label: 'Presupuesto de Azure (USD al mes)', hint: '0 = sin presupuesto.' },
      { k: 'presupuesto_aws_usd', label: 'Presupuesto de AWS (USD al mes)', hint: '0 = sin presupuesto.' },
    ],
  },
  {
    id: 'riesgo', titulo: 'Riesgo', descripcion: 'Reglas del catálogo que no se evalúan: sus hallazgos se cierran con una nota y no cuentan en los controles. Se aplica desde la próxima recolección.',
    campos: [
      { k: 'reglas_desactivadas', label: 'Reglas desactivadas', hint: 'Identificadores separados por comas, por ejemplo network.admin-port-open. Los ves en Riesgo → Cumplimiento → Catálogo de reglas.' },
    ],
  },
  {
    id: 'chequeos', titulo: 'Chequeos HTTP', descripcion: 'URLs que se revisan cada 10 minutos. Dos fallas seguidas (sin respuesta o 5xx) abren un incidente con diagnóstico; al responder se resuelve.',
    campos: [
      { k: 'urls', label: 'URLs', hint: 'Solo https, separadas por comas (hasta 20). No se revisan direcciones privadas ni locales.' },
    ],
  },
  {
    id: 'avisos', titulo: 'Avisos', descripcion: 'El motor de avisos común. En modo registro envía todo como antes y anota lo que habría silenciado o descartado; en modo activo aplica los silencios y descarta duplicados.',
    campos: [
      { k: 'modo', label: 'Modo', hint: 'Revisa Operación → Avisos una semana en modo registro antes de activarlo.' },
      { k: 'deduplicar_min', label: 'Descartar duplicados (minutos)', hint: 'Un aviso con la misma clave dentro de esta ventana no se repite. 0 = nunca.' },
      ...(['inicio', 'activos', 'costos', 'riesgo', 'operacion', 'plataforma'] as const).map((d) => ({
        k: `minimo_${d}`, label: `Severidad mínima · ${{ inicio: 'Inicio', activos: 'Activos', costos: 'Costos', riesgo: 'Riesgo', operacion: 'Operación', plataforma: 'Plataforma' }[d]}`,
        hint: 'Lo de menor severidad de este dominio no llega al canal (queda en Operación → Avisos). info = todo.',
      })),
    ],
  },
  {
    id: 'ia', titulo: 'Inteligencia artificial', descripcion: 'Tope de consultas al modelo de cada persona y de cada uso automático (diagnósticos, resúmenes). Sin modelo, todo sigue funcionando con las reglas.',
    campos: [
      { k: 'max_consultas_hora', label: 'Consultas por hora', hint: '0 = sin tope.' },
      { k: 'max_consultas_dia', label: 'Consultas por día', hint: '0 = sin tope.' },
    ],
  },
];

function SeccionGenerica({ def, data, onGuardado }: { def: (typeof SECCIONES)[number]; data: SeccionApi; onGuardado: () => void }) {
  const { can, toast } = useApp();
  const texto = (v: Valor) => (Array.isArray(v) ? v.join(', ') : String(v));
  const [borrador, setBorrador] = useState<Record<string, string> | null>(null);
  const [fallo, setFallo] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);
  const editar = can('administrador');
  const v = borrador ?? Object.fromEntries(def.campos.map((c) => [c.k, texto(data.values[c.k])]));

  const guardar = async () => {
    setGuardando(true);
    setFallo(null);
    const tipo = (k: string) => data.schema[k][0];
    const lista = (k: string) => tipo(k) === 'nombres' || tipo(k) === 'urls';
    const cuerpo = Object.fromEntries(def.campos.map((c) => [c.k, lista(c.k)
      ? v[c.k].split(',').map((x) => x.trim()).filter(Boolean)
      : tipo(c.k) === 'opcion' ? v[c.k] : Number(v[c.k])]));
    try {
      await put(`/api/settings/${def.id}`, cuerpo);
      toast(`${def.titulo}: ajustes guardados`);
      setBorrador(null);
      onGuardado();
    } catch (e) {
      setFallo(e instanceof Error ? e.message : String(e));
    } finally {
      setGuardando(false);
    }
  };

  return (
    <Section title={def.titulo} description={def.descripcion} actions={<Badge>{ORIGEN[data.origin].split(':')[0]}</Badge>}>
      <Card footer={editar ? (
        <>
          <span className="secondary">{borrador ? 'Hay cambios sin guardar.' : data.origin === 'variable' ? ORIGEN.variable : 'Sin cambios.'}</span>
          <div className="row-actions">
            <button className="btn btn-sm" disabled={!borrador || guardando} onClick={() => { setBorrador(null); setFallo(null); }}>Descartar</button>
            <button className="btn btn-primary btn-sm" disabled={!borrador || guardando} onClick={guardar}>Guardar</button>
          </div>
        </>
      ) : undefined}>
        <div className="grid grid-2" style={{ gap: 12 }}>
          {def.campos.map((c) => {
            const esquema = data.schema[c.k];
            if (esquema[0] === 'opcion') {
              return (
                <label className="field" key={c.k}>
                  {c.label}
                  <select className="select" disabled={!editar} value={v[c.k]} onChange={(e) => setBorrador({ ...v, [c.k]: e.target.value })}>
                    {esquema.slice(1).map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
                  </select>
                  <span className="hint">{c.hint}</span>
                </label>
              );
            }
            const numero = esquema[0] !== 'nombres' && esquema[0] !== 'urls';
            return (
              <label className="field" key={c.k}>
                {c.label}
                <input className="input" disabled={!editar} type={numero ? 'number' : 'text'} step={data.schema[c.k][0] === 'float' ? '0.01' : '1'}
                  min={numero ? Number(data.schema[c.k][1]) : undefined} max={numero ? Number(data.schema[c.k][2]) : undefined}
                  value={v[c.k]} onChange={(e) => setBorrador({ ...v, [c.k]: e.target.value })} />
                <span className="hint">{c.hint}</span>
              </label>
            );
          })}
        </div>
        {fallo && <div style={{ marginTop: 12 }}><Notice tone="critical">{fallo}</Notice></div>}
      </Card>
    </Section>
  );
}

const NOMBRE_SECCION: Record<string, string> = { incidentes: 'Incidentes', gobierno: 'Gobierno', costos: 'Costos', riesgo: 'Riesgo', avisos: 'Avisos', ia: 'Inteligencia artificial' };

function resumen(c: Cambio): string {
  const claves = Object.keys(c.despues).filter((k) => JSON.stringify(c.antes[k]) !== JSON.stringify(c.despues[k]));
  if (!claves.length) return 'Sin cambios de valor';
  return claves.map((k) => `${k}: ${JSON.stringify(c.antes[k])} → ${JSON.stringify(c.despues[k])}`).join(' · ');
}

function Historial({ onCambio }: { onCambio: () => void }) {
  const { can, toast } = useApp();
  const { data, error, loading, reload } = useApi<{ items: Cambio[] }>('settings-history', () => get('/api/settings-history'));
  const [enviando, setEnviando] = useState(false);
  if (loading) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  const items = data?.items ?? [];

  const deshacer = async (i: number) => {
    setEnviando(true);
    try {
      await post(`/api/settings-history/${i}/undo`, {});
      toast('Cambio deshecho');
      reload();
      onCambio();
    } catch (e) {
      toast(`No se pudo deshacer: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setEnviando(false);
    }
  };

  return (
    <Section title="Historial de cambios" description="Los últimos 50 cambios, con el antes y el después. Deshacer vuelve la sección a como estaba antes de ese cambio (y también queda registrado).">
      {items.length === 0 ? <Card><Empty>Todavía nadie cambió un ajuste.</Empty></Card> : (
        <Card flush>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Cuándo</th><th>Quién</th><th>Sección</th><th>Cambio</th><th /></tr></thead>
              <tbody>
                {items.map((c, i) => (
                  <tr key={`${c.at}-${i}`}>
                    <td className="secondary" style={{ whiteSpace: 'nowrap' }}>{dateTime(c.at)}</td>
                    <td className="secondary">{c.actor}</td>
                    <td>{c.seccion.startsWith('cluster:') ? `Kubernetes · ${c.seccion.slice(8)}` : NOMBRE_SECCION[c.seccion] ?? c.seccion}</td>
                    <td className="mono secondary" style={{ fontSize: 12 }}>{resumen(c)}</td>
                    <td>{can('administrador') && <button className="btn btn-ghost btn-sm" disabled={enviando} onClick={() => deshacer(i)}>Deshacer</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </Section>
  );
}

/** Plataforma → Ajustes: una sección por dominio, con su origen, y el historial con deshacer. */
export function SettingsPage({ onGo }: { onGo: (path: string) => void }) {
  const { can } = useApp();
  const { data, error, loading, reload } = useApi<{ sections: Record<string, SeccionApi> }>('settings', () => get('/api/settings'));
  const [version, setVersion] = useState(0);
  const recargar = () => { reload(); setVersion((n) => n + 1); };
  if (loading) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <>
      <PageHeader title="Ajustes" description="Las reglas y umbrales de cada dominio. Los cambia un administrador; cada cambio queda en el historial y en la auditoría." />
      <div className="stack" style={{ gap: 24 }}>
        {!can('administrador') && <Notice>Cambiar los ajustes requiere el rol Administrador.</Notice>}
        <IncidentSettingsView key={`incidentes-${version}`} />
        {SECCIONES.map((def) => data.sections[def.id] && (
          <SeccionGenerica key={`${def.id}-${version}`} def={def} data={data.sections[def.id]} onGuardado={recargar} />
        ))}
        <Notice>
          Los ajustes de cada clúster (namespaces ignorados, umbrales y avisos) están al final de su detalle:{' '}
          <button className="btn btn-ghost btn-sm" onClick={() => onGo('activos/kubernetes')}>Activos → Kubernetes</button>. Sus cambios también aparecen en el historial.
        </Notice>
        <ChecksStatus version={version} />
        <Historial key={`historial-${version}`} onCambio={recargar} />
      </div>
    </>
  );
}

import { useState } from 'react';
import { get, put } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import type { K8sClusterSettings, Severity } from '../../lib/types';
import { useApp } from '../../state/hooks';
import { Card, ErrorState, Loading, Notice, Section } from '../../components/ui';

const SEVERIDADES: { id: Severity; label: string }[] = [{ id: 'critica', label: 'Crítica' }, { id: 'alta', label: 'Alta' }, { id: 'media', label: 'Media' }];

/** Ajustes de un clúster: qué cuenta como incidencia y qué se avisa. Los cambia un administrador. */
export function ClusterSettings({ nombre, onGuardado }: { nombre: string; onGuardado: () => void }) {
  const { can, toast } = useApp();
  const { data, error, loading, reload } = useApi<{ values: K8sClusterSettings }>(
    `k8s-settings-${nombre}`, () => get(`/api/settings/k8s/${encodeURIComponent(nombre)}`));
  const [borrador, setBorrador] = useState<(K8sClusterSettings & { ns: string }) | null>(null);
  const [fallo, setFallo] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);
  if (loading) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  const v = borrador ?? { ...data.values, ns: data.values.namespaces_ignorados.join(', ') };
  const editar = can('administrador');
  const cambiar = (p: Partial<typeof v>) => setBorrador({ ...v, ...p });

  const guardar = async () => {
    setGuardando(true);
    setFallo(null);
    const { ns, ...valores } = v;
    try {
      await put(`/api/settings/k8s/${encodeURIComponent(nombre)}`, {
        ...valores, namespaces_ignorados: ns.split(',').map((x) => x.trim()).filter(Boolean),
      });
      toast('Ajustes del clúster guardados');
      setBorrador(null);
      reload();
      onGuardado();
    } catch (e) {
      setFallo(e instanceof Error ? e.message : String(e));
    } finally {
      setGuardando(false);
    }
  };

  return (
    <Section title="Ajustes del clúster" description="Qué cuenta como incidencia y qué avisa el vigilante cada 10 minutos.">
      <Card footer={editar ? (
        <>
          <span className="secondary">{borrador ? 'Hay cambios sin guardar.' : 'Sin cambios.'}</span>
          <div className="row-actions">
            <button className="btn btn-sm" disabled={!borrador || guardando} onClick={() => { setBorrador(null); setFallo(null); }}>Descartar</button>
            <button className="btn btn-primary btn-sm" disabled={!borrador || guardando} onClick={guardar}>Guardar</button>
          </div>
        </>
      ) : undefined}>
        <div className="stack" style={{ gap: 16 }}>
          {!editar && <Notice>Cambiar los ajustes requiere el rol Administrador.</Notice>}
          <label className="field">
            Namespaces ignorados
            <input className="input" disabled={!editar} value={v.ns} onChange={(e) => cambiar({ ns: e.target.value })} placeholder="Ninguno" />
            <span className="hint">Separados por comas. Sus pods, cargas y servicios no generan incidencias (por ejemplo, un namespace de pruebas).</span>
          </label>
          <div className="grid grid-2" style={{ gap: 12 }}>
            <label className="field">
              Reinicios para "reinicios frecuentes"
              <input className="input" type="number" min={1} max={100} disabled={!editar} value={v.reinicios} onChange={(e) => cambiar({ reinicios: Number(e.target.value) })} />
              <span className="hint">Más que esto, con el último en la última hora.</span>
            </label>
            <label className="field">
              Gracia de un pod nuevo (minutos)
              <input className="input" type="number" min={1} max={120} disabled={!editar} value={v.gracia_min} onChange={(e) => cambiar({ gracia_min: Number(e.target.value) })} />
              <span className="hint">Antes, un pod pendiente o sin estar listo se considera arrancando.</span>
            </label>
          </div>
          <label className="check">
            <input type="checkbox" disabled={!editar} checked={v.avisar} onChange={(e) => cambiar({ avisar: e.target.checked })} />
            Avisar las incidencias de este clúster al canal
          </label>
          {v.avisar && (
            <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
              <legend>Severidades que se avisan</legend>
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                {SEVERIDADES.map((s) => (
                  <label className="check" key={s.id}>
                    <input type="checkbox" disabled={!editar} checked={v.avisar_severidades.includes(s.id)} onChange={() => cambiar({
                      avisar_severidades: v.avisar_severidades.includes(s.id) ? v.avisar_severidades.filter((x) => x !== s.id) : [...v.avisar_severidades, s.id],
                    })} /> {s.label}
                  </label>
                ))}
              </div>
            </fieldset>
          )}
          {fallo && <Notice tone="critical">{fallo}</Notice>}
        </div>
      </Card>
    </Section>
  );
}

import { useState } from 'react';
import { get, put } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import type { IncidentSettings, Severity } from '../../lib/types';
import { useApp } from '../../state/hooks';
import { Card, ErrorState, Loading, Notice, Section } from '../../components/ui';

const SEVERIDADES: { id: Severity; label: string }[] = [{ id: 'critica', label: 'Crítica' }, { id: 'alta', label: 'Alta' }, { id: 'media', label: 'Media' }];
const NUMEROS: { k: 'ventana_tormenta_seg' | 'umbral_tormenta' | 'foto_vieja_min' | 'max_diagnosticos_hora'; label: string; hint: string }[] = [
  { k: 'ventana_tormenta_seg', label: 'Ventana de tormenta (segundos)', hint: 'Incidentes del mismo clúster abiertos dentro de esta ventana cuentan como una tormenta.' },
  { k: 'umbral_tormenta', label: 'Incidentes para una tormenta', hint: 'Desde cuántos se agrupan: el primero se diagnostica por todos y el resto no se avisa.' },
  { k: 'foto_vieja_min', label: 'Foto vieja (minutos)', hint: 'Una foto de Kubernetes más antigua se marca "sin reportar" y el diagnóstico lo advierte.' },
  { k: 'max_diagnosticos_hora', label: 'Tope de diagnósticos por hora', hint: '0 usa el tope general del modelo. Incluye los post-mortem.' },
];

/** Ajustes de incidentes: los cambia un administrador; se aplican a la siguiente alerta. */
export function IncidentSettingsView() {
  const { can, toast } = useApp();
  const { data, error, loading, reload } = useApi<{ values: IncidentSettings; limits: Record<string, [number, number]> }>(
    'incident-settings', () => get('/api/settings/incidents'));
  const [borrador, setBorrador] = useState<IncidentSettings | null>(null);
  const [fallo, setFallo] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);
  if (loading) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  const v = borrador ?? data.values;
  const editar = can('administrador');
  const cambiar = (p: Partial<IncidentSettings>) => setBorrador({ ...v, ...p });
  const alternar = (k: 'diagnosticar' | 'avisar', s: Severity) =>
    cambiar({ [k]: v[k].includes(s) ? v[k].filter((x) => x !== s) : [...v[k], s] });

  const guardar = async () => {
    setGuardando(true);
    setFallo(null);
    try {
      await put('/api/settings/incidents', v);
      toast('Ajustes guardados');
      setBorrador(null);
      reload();
    } catch (e) {
      setFallo(e instanceof Error ? e.message : String(e));
    } finally {
      setGuardando(false);
    }
  };

  return (
    <Section title="Ajustes de incidentes" description="Se aplican a las alertas que lleguen desde ahora.">
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
          <div className="grid grid-2" style={{ gap: 12 }}>
            {NUMEROS.map(({ k, label, hint }) => (
              <label className="field" key={k}>
                {label}
                <input className="input" type="number" disabled={!editar} min={data.limits[k]?.[0]} max={data.limits[k]?.[1]}
                  value={v[k]} onChange={(e) => cambiar({ [k]: Number(e.target.value) })} />
                <span className="hint">{hint}</span>
              </label>
            ))}
          </div>
          {(['diagnosticar', 'avisar'] as const).map((k) => (
            <fieldset key={k} className="field" style={{ border: 0, padding: 0, margin: 0 }}>
              <legend>{k === 'diagnosticar' ? 'Severidades que diagnostica el agente' : 'Severidades que se avisan al canal'}</legend>
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                {SEVERIDADES.map((s) => (
                  <label className="check" key={s.id}>
                    <input type="checkbox" disabled={!editar} checked={v[k].includes(s.id)} onChange={() => alternar(k, s.id)} /> {s.label}
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
          <label className="check">
            <input type="checkbox" disabled={!editar} checked={v.postmortem} onChange={(e) => cambiar({ postmortem: e.target.checked })} />
            Redactar el borrador de post-mortem al resolverse
          </label>
          {fallo && <Notice tone="critical">{fallo}</Notice>}
        </div>
      </Card>
    </Section>
  );
}

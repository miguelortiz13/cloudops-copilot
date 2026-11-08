import { Notice, PageHeader } from '../../components/ui';
import { IncidentSettingsView } from '../incidents/IncidentSettingsView';

/**
 * Plataforma → Ajustes. Fase 1: los de incidentes; en la fase 2 del plan
 * (docs/plan/10-reestructuracion-por-dominios.md) suma una sección por dominio.
 */
export function SettingsPage({ onGo }: { onGo: (path: string) => void }) {
  return (
    <>
      <PageHeader title="Ajustes" description="Las reglas y umbrales de la plataforma que cambia un administrador. Cada cambio queda en la auditoría y se aplica desde ese momento." />
      <div className="stack" style={{ gap: 24 }}>
        <IncidentSettingsView />
        <Notice>
          Los ajustes de cada clúster (namespaces ignorados, umbrales y avisos) siguen en su página, al final del detalle:{' '}
          <button className="btn btn-ghost btn-sm" onClick={() => onGo('activos/kubernetes')}>Activos → Kubernetes</button>.
        </Notice>
      </div>
    </>
  );
}

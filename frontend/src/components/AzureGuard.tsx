import type { ReactNode } from 'react';
import { useApp } from '../state/hooks';
import { Notice } from './ui';

/**
 * Las vistas en vivo consultan Azure (Resource Graph, Cost Management). Si el
 * filtro no incluye ninguna suscripción de Azure no se montan: no hay nada que
 * consultar y mostrar "todas" engañaría.
 */
export function AzureGuard({ children }: { children: ReactNode }) {
  const { azureNone } = useApp();
  if (azureNone) {
    return (
      <Notice>
        Esta vista consulta Azure en vivo y el filtro no incluye ninguna suscripción de Azure. Para las demás nubes,
        usa Seguridad → Gestión, Costos → Historial, Cumplimiento y Reportes.
      </Notice>
    );
  }
  return <>{children}</>;
}

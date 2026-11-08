import { PageHeader } from '../../components/ui';
import { AzureGuard } from '../../components/AzureGuard';
import { CostsView } from './CostsView';
import { HistoryView } from './HistoryView';
import { SavingsView } from './SavingsView';

type View = 'costos' | 'historial' | 'ahorro';

const CABECERA: Record<View, { title: string; description: string }> = {
  costos: { title: 'Gasto', description: 'Cuánto cuesta la nube este mes, cómo va contra el anterior y en qué se va el dinero: por servicio, cuenta, recurso y etiqueta.' },
  historial: { title: 'Historial', description: 'La historia propia de costos de la plataforma: tendencia diaria, comparación entre periodos y desglose por cuenta, servicio y recurso.' },
  ahorro: { title: 'Ahorro', description: 'Oportunidades de ahorro de Azure Advisor y de la plataforma, con su monto estimado y lo que ya se resolvió.' },
};

/** Costos: una sección por vista (Gasto, Historial, Ahorro). */
export function FinOpsPage({ view }: { view: string | undefined }) {
  const active: View = view === 'ahorro' || view === 'historial' ? view : 'costos';
  return (
    <>
      <PageHeader {...CABECERA[active]} />
      {active === 'costos' && <AzureGuard><CostsView /></AzureGuard>}
      {active === 'historial' && <HistoryView />}
      {active === 'ahorro' && <AzureGuard><SavingsView /></AzureGuard>}
    </>
  );
}

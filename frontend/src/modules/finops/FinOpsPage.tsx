import { PageHeader, Tabs } from '../../components/ui';
import { CostsView } from './CostsView';
import { SavingsView } from './SavingsView';

type View = 'costos' | 'ahorro';

export function FinOpsPage({ view, onView }: { view: string | undefined; onView: (v: View) => void }) {
  const active: View = view === 'ahorro' ? 'ahorro' : 'costos';
  return (
    <>
      <PageHeader
        title="Costos"
        description="Cuánto cuesta la nube, cómo evoluciona y en qué se va el dinero. Las oportunidades de ahorro están en su propia pestaña, para leerlas con el gasto total en contexto."
      />
      <Tabs<View>
        value={active}
        onChange={onView}
        tabs={[
          { id: 'costos', label: 'Visión general' },
          { id: 'ahorro', label: 'Optimización y ahorro' },
        ]}
      />
      {active === 'costos' ? <CostsView /> : <SavingsView />}
    </>
  );
}

import { useEffect, useState } from 'react';
import { Cloud } from 'lucide-react';
import { authEnabled, initAuth, login } from './auth';
import { AppProvider } from './state/AppContext';
import { useApp, useRoute } from './state/hooks';
import { AgentDock, Sidebar, SyncDialog, Topbar } from './components/layout';
import { NAV } from './components/nav';
import { SectionBoundary } from './components/SectionBoundary';
import { OverviewPage } from './modules/overview/OverviewPage';
import { InventoryPage } from './modules/inventory/InventoryPage';
import { FinOpsPage } from './modules/finops/FinOpsPage';
import { SecOpsPage } from './modules/secops/SecOpsPage';
import { IacPage } from './modules/iac/IacPage';
import { IsoPage } from './modules/iso/IsoPage';
import { ReportsPage } from './modules/reports/ReportsPage';

const LABELS: Record<string, string> = Object.fromEntries(NAV.flatMap((g) => g.items.map((i) => [i.id, i.label])));
const SUBVIEWS: Record<string, string> = {
  costos: 'Visión general', historial: 'Historial y comparación', ahorro: 'Optimización y ahorro', gestion: 'Gestión de hallazgos',
};

function Shell() {
  const [route, navigate] = useRoute();
  const { toasts, setDockAgent } = useApp();
  const [mobileNav, setMobileNav] = useState(false);
  const [syncOpen, setSyncOpen] = useState(false);
  const page = LABELS[route[0]] ? route[0] : 'resumen';
  const sub = route[1];

  useEffect(() => {
    document.title = `${LABELS[page]} · CloudOps Copilot`;
    window.scrollTo(0, 0);
    // La consola se sintoniza con la sección: casi siempre es el agente que se quiere.
    const agente = { finops: 'finops', secops: 'secops' }[page] ?? 'inventory';
    setDockAgent(agente as 'finops' | 'secops' | 'inventory');
  }, [page, setDockAgent]);

  const trail = ['CloudOps Copilot', LABELS[page], ...((page === 'finops' || page === 'secops') && sub && SUBVIEWS[sub] ? [SUBVIEWS[sub]] : [])];

  return (
    <div className="shell">
      <Sidebar active={page} mobileOpen={mobileNav} onNavigate={() => setMobileNav(false)} />
      {mobileNav && <div className="overlay" onClick={() => setMobileNav(false)} />}
      <div className="main">
        <Topbar trail={trail} onMenu={() => setMobileNav(true)} onSync={() => setSyncOpen(true)} />
        <main className="content">
          <SectionBoundary name={LABELS[page]} key={page}>
            {page === 'resumen' && <OverviewPage />}
            {page === 'inventario' && <InventoryPage />}
            {page === 'finops' && <FinOpsPage view={sub} onView={(v) => navigate(`finops/${v}`)} />}
            {page === 'secops' && <SecOpsPage view={sub} onView={(v) => navigate(`secops/${v}`)} />}
            {page === 'iac' && <IacPage />}
            {page === 'iso' && <IsoPage />}
            {page === 'reportes' && <ReportsPage onSync={() => setSyncOpen(true)} />}
          </SectionBoundary>
        </main>
      </div>
      <AgentDock />
      {syncOpen && <SyncDialog onClose={() => setSyncOpen(false)} />}
      <div className="toast-stack" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className="toast">{t.text}</div>)}
      </div>
    </div>
  );
}

/**
 * Resuelve la sesión de Entra ID antes de pedir datos: con AUTH_ENABLED el API
 * responde 401 sin token, y lanzar las consultas antes solo produce un panel
 * vacío. Sin autenticación configurada arranca directo.
 */
export default function App() {
  const [ready, setReady] = useState(!authEnabled);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authEnabled) return;
    initAuth()
      .then((account) => (account ? setReady(true) : login()))
      .catch((e) => {
        console.error(e);
        setError('No se pudo iniciar sesión con Microsoft Entra ID.');
      });
  }, []);

  if (!ready) {
    return (
      <div className="center-screen">
        <div className="stack" style={{ alignItems: 'center' }}>
          <div className="brand-mark" style={{ width: 40, height: 40, borderRadius: 10 }}><Cloud size={20} /></div>
          <div className="page-title" style={{ fontSize: 18 }}>CloudOps Copilot</div>
          <span className="secondary">{error ?? 'Iniciando sesión con Microsoft Entra ID…'}</span>
          {error ? <button className="btn btn-primary" onClick={() => login()}>Reintentar</button> : <div className="spinner" />}
        </div>
      </div>
    );
  }

  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}

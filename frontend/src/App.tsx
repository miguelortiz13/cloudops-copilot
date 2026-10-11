import { lazy, Suspense, useEffect, useState } from 'react';
import { Cloud } from 'lucide-react';
import { authEnabled, initAuth, login } from './auth';
import { AppProvider } from './state/AppContext';
import { useApp, useRoute } from './state/hooks';
import { AgentDock, Sidebar, SyncDialog, Topbar } from './components/layout';
import { NAV } from './components/nav';
import { SectionBoundary } from './components/SectionBoundary';
import { Loading } from './components/ui';

// Cada sección se descarga al abrirla: la carga inicial no paga por módulos
// que el usuario quizá no visite (gráficos, tablas, gestión, administración).
const OverviewPage = lazy(() => import('./modules/overview/OverviewPage').then((m) => ({ default: m.OverviewPage })));
const InventoryPage = lazy(() => import('./modules/inventory/InventoryPage').then((m) => ({ default: m.InventoryPage })));
const FinOpsPage = lazy(() => import('./modules/finops/FinOpsPage').then((m) => ({ default: m.FinOpsPage })));
const SecOpsPage = lazy(() => import('./modules/secops/SecOpsPage').then((m) => ({ default: m.SecOpsPage })));
const IacPage = lazy(() => import('./modules/iac/IacPage').then((m) => ({ default: m.IacPage })));
const CompliancePage = lazy(() => import('./modules/compliance/CompliancePage').then((m) => ({ default: m.CompliancePage })));
const ReportsPage = lazy(() => import('./modules/reports/ReportsPage').then((m) => ({ default: m.ReportsPage })));
const AdminPage = lazy(() => import('./modules/admin/AdminPage').then((m) => ({ default: m.AdminPage })));

const LABELS: Record<string, string> = Object.fromEntries(NAV.flatMap((g) => g.items.map((i) => [i.id, i.label])));
const SUBVIEWS: Record<string, string> = {
  costos: 'Visión general', historial: 'Historial y comparación', ahorro: 'Optimización y ahorro', gestion: 'Gestión de hallazgos',
  actividad: 'Actividad de usuarios', cuentas: 'Cuentas conectadas', plataforma: 'Base y recolectores',
  controles: 'Controles', reglas: 'Catálogo de reglas', activos: 'Clasificación de activos',
};

function Shell() {
  const [route, navigate] = useRoute();
  const { toasts, setDockAgent } = useApp();
  const [mobileNav, setMobileNav] = useState(false);
  const [syncOpen, setSyncOpen] = useState(false);
  // `iso` era la ruta anterior de Cumplimiento: los enlaces guardados siguen sirviendo.
  const page = LABELS[route[0]] ? route[0] : route[0] === 'iso' ? 'cumplimiento' : 'resumen';
  const sub = route[1];

  useEffect(() => {
    document.title = `${LABELS[page]} · CloudOps Copilot`;
    window.scrollTo(0, 0);
    // La consola se sintoniza con la sección: casi siempre es el agente que se quiere.
    const agente = { finops: 'finops', secops: 'secops' }[page] ?? 'inventory';
    setDockAgent(agente as 'finops' | 'secops' | 'inventory');
  }, [page, setDockAgent]);

  const trail = ['CloudOps Copilot', LABELS[page], ...((page === 'finops' || page === 'secops' || page === 'admin' || page === 'cumplimiento') && sub && SUBVIEWS[sub] ? [SUBVIEWS[sub]] : [])];

  return (
    <div className="shell">
      <Sidebar active={page} mobileOpen={mobileNav} onNavigate={() => setMobileNav(false)} />
      {mobileNav && <div className="overlay" onClick={() => setMobileNav(false)} />}
      <div className="main">
        <Topbar trail={trail} onMenu={() => setMobileNav(true)} onSync={() => setSyncOpen(true)} />
        <main className="content">
          <SectionBoundary name={LABELS[page]} key={page}>
            <Suspense fallback={<Loading />}>
            {page === 'resumen' && <OverviewPage />}
            {page === 'inventario' && <InventoryPage />}
            {page === 'finops' && <FinOpsPage view={sub} onView={(v) => navigate(`finops/${v}`)} />}
            {page === 'secops' && <SecOpsPage view={sub} onView={(v) => navigate(`secops/${v}`)} />}
            {page === 'iac' && <IacPage />}
            {page === 'cumplimiento' && <CompliancePage view={sub} onView={(v) => navigate(`cumplimiento/${v}`)} onGo={navigate} />}
            {page === 'reportes' && <ReportsPage onSync={() => setSyncOpen(true)} />}
            {page === 'admin' && <AdminPage view={sub} onView={(v) => navigate(`admin/${v}`)} />}
            </Suspense>
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

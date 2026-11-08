import { lazy, Suspense, useEffect, useState } from 'react';
import { Cloud } from 'lucide-react';
import { authEnabled, initAuth, login } from './auth';
import { AppProvider } from './state/AppContext';
import { useApp, useRoute } from './state/hooks';
import { AgentDock, Sidebar, SyncDialog, Topbar } from './components/layout';
import { ETIQUETA, resolver } from './components/nav';
import { AzureGuard } from './components/AzureGuard';
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
const KubernetesPage = lazy(() => import('./modules/kubernetes/KubernetesPage').then((m) => ({ default: m.KubernetesPage })));
const IncidentsPage = lazy(() => import('./modules/incidents/IncidentsPage').then((m) => ({ default: m.IncidentsPage })));
const ReportsPage = lazy(() => import('./modules/reports/ReportsPage').then((m) => ({ default: m.ReportsPage })));
const AdminPage = lazy(() => import('./modules/admin/AdminPage').then((m) => ({ default: m.AdminPage })));
const SilencesPage = lazy(() => import('./modules/incidents/SilencesView').then((m) => ({ default: m.SilencesPage })));
const SettingsPage = lazy(() => import('./modules/settings/SettingsPage').then((m) => ({ default: m.SettingsPage })));

function Shell() {
  const [route, navigate] = useRoute();
  const { toasts, setDockAgent } = useApp();
  const [mobileNav, setMobileNav] = useState(false);
  const [syncOpen, setSyncOpen] = useState(false);
  const destino = resolver(route);
  const seccion = 'seccion' in destino ? destino.seccion : null;
  const [sub] = 'resto' in destino ? destino.resto : [];
  const etiqueta = seccion ? ETIQUETA[seccion] : null;

  // Rutas anteriores a los dominios (enlaces guardados, avisos ya enviados): a su sección nueva, sin dejar
  // la vieja en el historial.
  useEffect(() => {
    if ('redirigir' in destino) window.location.replace(`#/${destino.redirigir}`);
  });

  useEffect(() => {
    if (!seccion) return;
    document.title = `${ETIQUETA[seccion].seccion} · CloudOps Copilot`;
    window.scrollTo(0, 0);
    // La consola se sintoniza con el dominio: casi siempre es el agente que se quiere.
    const agente = seccion === 'activos/kubernetes' ? 'k8s' : { costos: 'finops', riesgo: 'secops' }[seccion.split('/')[0]] ?? 'inventory';
    setDockAgent(agente as 'finops' | 'secops' | 'inventory' | 'k8s');
  }, [seccion, setDockAgent]);

  if (!seccion || !etiqueta) return null;
  const trail = ['CloudOps Copilot', etiqueta.dominio, etiqueta.seccion];

  return (
    <div className="shell">
      <Sidebar active={seccion} mobileOpen={mobileNav} onNavigate={() => setMobileNav(false)} />
      {mobileNav && <div className="overlay" onClick={() => setMobileNav(false)} />}
      <div className="main">
        <Topbar trail={trail} onMenu={() => setMobileNav(true)} onSync={() => setSyncOpen(true)} />
        <main className="content">
          <SectionBoundary name={etiqueta.seccion} key={seccion}>
            <Suspense fallback={<Loading />}>
            {seccion === 'inicio/resumen' && <AzureGuard><OverviewPage /></AzureGuard>}
            {seccion === 'activos/inventario' && <AzureGuard><InventoryPage /></AzureGuard>}
            {seccion === 'activos/iac' && <AzureGuard><IacPage /></AzureGuard>}
            {seccion === 'activos/kubernetes' && <KubernetesPage cluster={sub} onCluster={(c) => navigate(`activos/kubernetes/${c}`)} onIncidente={(i) => navigate(`operacion/incidentes/${i}`)} />}
            {seccion === 'costos/gasto' && <FinOpsPage view="costos" />}
            {seccion === 'costos/historial' && <FinOpsPage view="historial" />}
            {seccion === 'costos/ahorro' && <FinOpsPage view="ahorro" />}
            {seccion === 'riesgo/hallazgos' && <SecOpsPage view="gestion" />}
            {seccion === 'riesgo/exposicion' && <SecOpsPage view="vivo" />}
            {seccion === 'riesgo/cumplimiento' && <CompliancePage view={sub} onView={(v) => navigate(`riesgo/cumplimiento/${v}`)} onGo={navigate} />}
            {seccion === 'riesgo/clasificacion' && <CompliancePage view="activos" onView={(v) => navigate(`riesgo/cumplimiento/${v}`)} onGo={navigate} />}
            {seccion === 'operacion/incidentes' && <IncidentsPage incidente={sub} onIncidente={(i) => navigate(`operacion/incidentes/${i}`)} />}
            {seccion === 'operacion/silencios' && <SilencesPage />}
            {seccion === 'plataforma/reportes' && <ReportsPage onSync={() => setSyncOpen(true)} />}
            {seccion === 'plataforma/ajustes' && <SettingsPage onGo={navigate} />}
            {seccion === 'plataforma/cuentas' && <AdminPage view="cuentas" />}
            {seccion === 'plataforma/auditoria' && <AdminPage view="actividad" />}
            {seccion === 'plataforma/estado' && <AdminPage view="plataforma" />}
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

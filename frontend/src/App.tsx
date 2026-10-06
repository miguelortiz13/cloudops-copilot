import React, { useState, useEffect, useRef } from 'react';
import { 
  LayoutDashboard, 
  RefreshCw, 
  Database, 
  CheckCircle, 
  AlertTriangle, 
  Terminal, 
  Send,
  Copy,
  Shield,
  FileText,
  Eye,
  Download,
  Search,
  X,
  Clipboard,
  Globe,
  Tag,
  Users,
  Layers,
  MapPin,
  MessageSquare
} from 'lucide-react';
import { apiFetch, authEnabled, initAuth, login } from './auth';
import { SectionBoundary } from './SectionBoundary';
import { TrendPanel, type HistorySeries } from './Trend';
import './App.css';

// URL del API. Se define en tiempo de compilación con VITE_API_URL
// (ver frontend/.env.example); en desarrollo apunta al backend local.
const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') || 'http://localhost:8000';

// Nombre que muestra el panel para la persona que lo usa.
const USER_NAME = (import.meta.env.VITE_USER_DISPLAY_NAME as string | undefined) || 'Operador';
const USER_ROLE = (import.meta.env.VITE_USER_ROLE as string | undefined) || 'DevOps Engineer';
const USER_INITIALS = USER_NAME.split(/\s+/).map(p => p[0]).join('').slice(0, 2).toUpperCase();

// Suscripción de relleno para construir ids cuando aún no hay ninguna elegida.
const PLACEHOLDER_SUBSCRIPTION = '00000000-0000-0000-0000-000000000000';

/**
 * Creaciones manuales con evidencia del historial de cambios de Azure.
 *
 * A diferencia del KPI de candidatos a Shadow IT —que solo constata que nadie
 * declaro el recurso— esto nombra a la identidad que lo creo. Azure conserva
 * esos eventos unos catorce dias, asi que la ventana observada viaja con el
 * dato y la interfaz la muestra siempre: es evidencia de lo reciente, nunca del
 * inventario historico.
 */
/**
 * Cobertura real de Terraform, leida de los estados.
 *
 * Sustituye al porcentaje de recursos con tag de IaC, que medía cuántos equipos
 * etiquetan y no cuánta infraestructura está codificada.
 */
interface TerraformCoverage {
  available: boolean;
  managed_in_inventory: number;
  total_resources: number;
  coverage_percentage: number;
  unmanaged_count: number;
  states_read: number;
  states_failed: number;
  managed_ids_total: number;
  stale_ids: number;
  states: { name: string; ok: boolean; resources: number; reason: string | null }[];
  message: string;
}

interface ManualCreation {
  id: string;
  name: string;
  type: string;
  createdBy: string;
  createdAt: string;
}

interface ManualCreations {
  manualCreations: ManualCreation[];
  manualCount: number;
  automatedCount: number;
  totalCreations: number;
  windowFrom: string | null;
  windowTo: string | null;
  available: boolean;
}

interface InventoryStats {
  total_resources: number;
  terraform_managed: number;
  portal_managed: number;
  unknown_managed: number;
  terraform_percentage: number;
  missing_owner_tags: number;
  missing_environment_tags: number;
  tag_compliance_percentage: number;
  top_subscriptions: Record<string, number>;
  domain_distribution: Record<string, number>;
  import_required: number;
  missing_tags_detail?: Record<string, number>;
  orphaned_disks?: number;
  orphaned_ips?: number;
  orphaned_nics?: number;
  exposed_nsgs?: number;
  failed_resources?: number;
  estimated_monthly_savings?: number;
}

interface Resource {
  name: string;
  type: string;
  resourceGroup: string;
  subscription_name: string;
  subscriptionId: string;
  location: string;
  environment: string;
  owner_confirmed: string;
  provisioning_method: string;
  requires_terraform_import: string;
  candidate_module: string;
  tagging_ok: string;
  tagging_details?: string;
  missing_tags?: string[];
  naming_ok: string;
  tags: string;
  id?: string;
}

// Full-scope FinOps report
interface FinOpsReport {
  unattached_disks: any[];
  unassociated_ips: any[];
  orphaned_nics: any[];
  empty_app_plans: any[];
  old_snapshots: any[];
  untagged_resources: any[];
  resources_by_rg: any[];
  estimated_savings_breakdown: Record<string, number>;
  savings_lifecycle?: {
    potential_savings_usd: number;
    approved_savings_usd: number;
    realized_savings_usd: number;
  };
  insights?: {
    showback_chargeback: any[];
    // El backend declara sobre qué parte del scope alcanza la atribución; la
    // interfaz tiene que poder decirlo en vez de presentar un total como si
    // cubriera todo el tenant.
    showback_status?: string;
    budgets: any[];
    budgets_status?: string;
    profiling_scope?: Record<string, any>;
    anomalies: any[];
    no_owner_resources: any[];
    underutilized_resources: any[];
    running_dev_vms_outside_hours: any[];
    reservation_recommendations: any[];
    aging_resources_no_expiration: any[];
  };
}

// Full-scope SecOps report
/**
 * Sintesis de SecOps y FinOps: cada hallazgo con el gasto del recurso expuesto.
 *
 * `cost_basis` distingue tres situaciones que no se pueden confundir:
 * 'actual' es gasto facturado, 'unavailable' es un recurso cuya suscripcion no
 * tiene cobertura de costo —vale desconocido, no cero— y 'not_applicable' marca
 * los hallazgos cuyo costo no es atribuible al recurso senalado, como una regla
 * de NSG, que no factura por si misma.
 */
interface RiskFinding {
  id: string;
  name: string;
  tipo: string;
  titulo: string;
  severidad: 'critica' | 'alta' | 'media';
  recomendacion?: string;
  monthly_cost_usd: number;
  cost_basis: 'actual' | 'unavailable' | 'not_applicable';
}

interface RiskExposure {
  findings: RiskFinding[];
  exposure_by_severity: Record<string, { resources: number; monthly_usd: number; measured: number; unmeasured: number }>;
  top_exposure: { id: string; name: string; tipo: string; severidad: string; monthly_cost_usd: number; cost_basis: string; hallazgos: number }[];
  totals: {
    findings: number;
    affected_resources: number;
    measured_resources: number;
    unmeasured_resources: number;
    monthly_usd_at_risk: number;
    currency: string;
  };
  coverage: { status: string; covered_count: number; uncovered_count: number; message: string };
}

interface SecOpsReport {
  exposed_nsgs: any[];
  public_storage_accounts: any[];
  exposed_keyvaults: any[];
  public_ips_active: any[];
  failed_resources: any[];
  vms_without_encryption: any[];
  attack_surface_summary: Record<string, number>;
}

// Los cuatro agentes de la plataforma. El de Kubernetes responde por su propio
// endpoint (/api/k8s/chat) porque su contexto lo arma K8sService contra el
// clúster, no contra Resource Graph.
type AgentType = 'inventory' | 'finops' | 'secops' | 'k8s';

/** Los cuatro agentes, en el orden en que aparecen en la consola. */
const AGENTES: { id: AgentType; icon: string; short: string; desc: string }[] = [
  { id: 'inventory', icon: '📋', short: 'Inventario', desc: 'Recursos, tags y gobernanza' },
  { id: 'finops', icon: '💰', short: 'FinOps', desc: 'Costos, ahorro y desperdicio' },
  { id: 'secops', icon: '🛡️', short: 'SecOps', desc: 'Exposición y salud operativa' },
  { id: 'k8s', icon: '☸️', short: 'Kubernetes', desc: 'Diagnóstico de clústeres AKS' },
];

interface ChatMessage {
  id: string;
  sender: 'user' | 'bot';
  text: string;
  timestamp: string;
  mode?: string;
}

// --- Inventory v2 Interfaces ---
interface InventoryV2Resource {
  id: string;
  name: string;
  type: string;
  typeDisplayName?: string;
  subscriptionId: string;
  subscriptionName: string;
  resourceGroup: string;
  location: string;
  kind?: string;
  skuName?: string;
  skuTier?: string;
  provisioningState?: string;
  createdTime?: string;
  changedTime?: string;
  managedBy?: string;
  tags: Record<string, string>;
  environment?: string;
  customer?: string;
  tenant?: string;
  platform?: string;
  product?: string;
  suite?: string;
  mandatoryTags: {
    totalRequired: number;
    present: number;
    missing: string[];
    compliancePercentage: number;
    isCompliant: boolean;
  };
  governance: {
    hasOwnerCandidate: boolean;
    ownerCandidate?: string;
    isProduction: boolean;
    isNonProduction: boolean;
    isShadowItCandidate: boolean;
    shadowItReason?: string;
    dataCompletenessScore: number;
  };
}

interface InventoryV2Summary {
  totalResources: number;
  totalSubscriptions: number;
  totalResourceGroups: number;
  totalRegions: number;
  tagCompliancePercentage: number;
  nonCompliantResources: number;
  shadowItCandidates: number;
  resourcesWithoutOwnerCandidate: number;
  productionResources: number;
  nonProductionResources: number;
  bySubscription: { key: string; count: number; percentage: number }[];
  byResourceType: { key: string; count: number; percentage: number }[];
  byRegion: { key: string; count: number; percentage: number }[];
  byEnvironment: { key: string; count: number; percentage: number }[];
  lastUpdated?: string;
  partialSuccess: boolean;
  warnings: string[];
}

interface TagComplianceMatrix {
  requiredTags: string[];
  matrix: { tag: string; present: number; missing: number; compliancePercentage: number }[];
  totalResources: number;
  overallCompliancePercentage: number;
  lastUpdated?: string;
  partialSuccess: boolean;
  warnings: string[];
}

interface InventoryV2Sub {
  subscriptionId: string;
  displayName: string;
  state: string;
  tenantId?: string;
}

export default function App() {
  const [activeTab, setActiveTab] = useState<'inventario' | 'finops' | 'secops' | 'iac' | 'iso' | 'k8s'>('inventario');
  const [stats, setStats] = useState<InventoryStats | null>(null);
  const [resources, setResources] = useState<Resource[]>([]);
  const [isoReport, setIsoReport] = useState<any | null>(null);
  const [loadingIso, setLoadingIso] = useState(false);
  const [searchQuery] = useState('');
  const [regionFilter] = useState('');
  const [taggingFilter] = useState('');
  
  // Pagination & Optimization states
  const [page, setPage] = useState(1);
  const [, setTotalResources] = useState(0);
  const [pageSize] = useState(50);
  const [manualResources, setManualResources] = useState<Resource[]>([]);
  const [manualCreations, setManualCreations] = useState<ManualCreations | null>(null);
  const [tfCoverage, setTfCoverage] = useState<TerraformCoverage | null>(null);
  
  // IaC & Terraform states
  const [selectedResourceForIaC, setSelectedResourceForIaC] = useState<Resource | null>(null);
  const [iacDomain, setIacDomain] = useState<'networking' | 'platform' | 'data' | 'security'>('platform');
  const [iacEnvironment, setIacEnvironment] = useState<'dev' | 'qa' | 'prod'>('dev');
  const [generatedIaCFiles, setGeneratedIaCFiles] = useState<any | null>(null);
  const [iacGenerating, setIacGenerating] = useState(false);
  const [iacModalOpen, setIacModalOpen] = useState(false);
  const [activeIaCFileTab, setActiveIaCFileTab] = useState<'main_tf' | 'providers_tf' | 'variables_tf' | 'outputs_tf' | 'terraform_tfvars' | 'backend_hcl'>('main_tf');
  
  // Snapshots states
  const [snapshots, setSnapshots] = useState<any[]>([]);
  const [, setLoadingSnapshots] = useState(false);
  

  
  // Specialized Chat states (Inventory, FinOps, SecOps)
  const [inventoryInput, setInventoryInput] = useState('');
  const [inventoryHistory, setInventoryHistory] = useState<ChatMessage[]>([
    {
      id: 'welcome-inv',
      sender: 'bot',
      text: '### 📋 Agente de Inventario & Gobernanza 👋\n\nHola. Soy tu agente especializado en el inventario general y cumplimiento de tags de tu inquilino Azure.\n\nPuedes hacerme preguntas sobre:\n- *¿Qué recursos están en el grupo de recursos `rg-plataforma-dev`?*\n- *¿Cuáles recursos no cumplen con las 6 etiquetas obligatorias?*\n- *Dibuja una tabla de los recursos en la región `eastus2` con sus tags*',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
  ]);
  const [isInventoryTyping, setIsInventoryTyping] = useState(false);

  const [finopsInput, setFinopsInput] = useState('');
  const [finopsHistory, setFinopsHistory] = useState<ChatMessage[]>([
    {
      id: 'welcome-fin',
      sender: 'bot',
      text: '### 💰 Agente FinOps & Optimización de Costos Cloud 💵\n\nHola. Soy tu **Agente FinOps de Alcance Completo** para Azure. Tengo visibilidad total de todos los recursos de la suscripción para ayudarte a reducir costos.\n\nMi cobertura incluye:\n- 💾 **Recursos huérfanos**: discos, IPs, NICs, snapshots sin uso\n- 📦 **Recursos ociosos**: App Service Plans vacíos, VMs subdimensionadas\n- 🏷️ **Puntos ciegos de costos**: recursos sin tags de imputación\n- 📊 **Distribución de costos**: por Resource Group, tipo de recurso, ambiente\n- 💡 **Estrategias FinOps**: right-sizing, auto-shutdown, reserved instances\n\nPregúntame lo que quieras, por ejemplo:\n- *¿Cuál es el reporte completo de desperdicio de esta suscripción?*\n- *¿Qué recursos del entorno dev se pueden apagar en horario no laboral?*\n- *Dame un plan de ahorro para reducir el 20% del gasto cloud este mes.*',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
  ]);
  const [isFinopsTyping, setIsFinopsTyping] = useState(false);

  const [secopsInput, setSecopsInput] = useState('');
  const [secopsHistory, setSecopsHistory] = useState<ChatMessage[]>([
    {
      id: 'welcome-sec',
      sender: 'bot',
      text: '### 🛡️ Agente SecOps & Salud Operativa Cloud 🩺\n\nHola. Soy tu **Agente SecOps de Alcance Completo** para Azure. Tengo visibilidad total de toda la postura de seguridad de la suscripción.\n\nMi cobertura incluye:\n- 🚨 **Exposición de red**: NSGs con puertos abiertos, superficie de ataque\n- 🗄️ **Exposición de datos**: Storage Accounts con blob público, Key Vaults sin private endpoint\n- 🖥️ **Compliance de compute**: VMs sin disk encryption, sin diagnostic settings\n- ❌ **Salud operativa**: recursos en estado Failed, despliegues fallidos\n- 🌐 **Inventario de IPs públicas**: todas las IPs activas y su justificación\n\nPregúntame lo que quieras, por ejemplo:\n- *Dame el reporte completo de seguridad de la suscripción con priorización de riesgos.*\n- *¿Qué recursos tienen mayor exposición a internet y cómo los protejo?*\n- *Genera los comandos Azure CLI para cerrar todos los puertos admin expuestos.*',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
  ]);
  const [isSecopsTyping, setIsSecopsTyping] = useState(false);
  const [k8sInput, setK8sInput] = useState(""); 
  const [k8sHistory, setK8sHistory] = useState<ChatMessage[]>([{ id: "welcome-k8s", sender: "bot", text: "### ☸️ Agente SRE Kubernetes 🚀\n\nHola. Soy tu **Agente Kubernetes SRE**. Tengo acceso en tiempo real a los clústeres AKS para diagnóstico avanzado sin requerir firewalls.\n\nMi cobertura incluye:\n- 🐳 **Diagnóstico de Pods**: CrashLoopBackOff, OOMKilled, Pending\n- 💻 **Salud de Nodos**: Presión, NotReady, Node Pools\n- 🌐 **Red & Servicios**: Ingress fallidos, Services sin endpoints\n- 🩺 **Estado**: Health Score y eventos críticos\n\nPregúntame lo que quieras, por ejemplo:\n- *Hazme un diagnóstico rápido del clúster aks-plataforma-dev.*\n- *¿Por qué hay servicios sin endpoints?*", timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) }]); 
  const [isK8sTyping, setIsK8sTyping] = useState(false);
  
  // Sync state
  const [syncRunning, setSyncRunning] = useState(false);
  const [syncLogs, setSyncLogs] = useState('');
  const [showSyncModal, setShowSyncModal] = useState(false);
  
  // App state
  const [isBackendConnected, setIsBackendConnected] = useState(false);
  const [showCopyNotification, setShowCopyNotification] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [toastType, setToastType] = useState<'success' | 'error' | 'info'>('success');

  const showToast = (msg: string, type: 'success' | 'error' | 'info' = 'success') => {
    setToastMessage(msg);
    setToastType(type);
    setTimeout(() => setToastMessage(null), 5000);
  };

  // Full-scope report states
  const [finopsReport, setFinopsReport] = useState<FinOpsReport | null>(null);
  const [secopsReport, setSecopsReport] = useState<SecOpsReport | null>(null);
  const [riskExposure, setRiskExposure] = useState<RiskExposure | null>(null);

  // Tendencia histórica de los KPIs. El backend la registra desde hace días y
  // el componente existía, pero nadie lo montaba ni llamaba al endpoint: la
  // serie se estaba acumulando sin que nadie pudiera verla.
  const [history, setHistory] = useState<HistorySeries | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);

  // Consola de agentes: una sola, disponible desde cualquier pestaña.
  // Antes cada pestaña incrustaba su propio chat —cuatro paneles con el mismo
  // componente dentro—, lo que partia el espacio util en dos y obligaba a
  // cambiar de sección para cambiar de agente. El agente por defecto sigue a la
  // pestaña activa, que es casi siempre el que se quiere preguntar.
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [consoleAgent, setConsoleAgent] = useState<AgentType>('inventory');

  // Teams integration states
  const [teamsWebhookUrl, setTeamsWebhookUrl] = useState(localStorage.getItem('teamsWebhookUrl') || '');
  const [teamsAlertType, setTeamsAlertType] = useState<'finops' | 'secops' | 'all'>('all');
  const [isSendingWebhook, setIsSendingWebhook] = useState(false);
  const [webhookStatus, setWebhookStatus] = useState<{ success: boolean; message: string } | null>(null);

  // Subscription Multi-Select Filter states
  const [subscriptionsList, setSubscriptionsList] = useState<{ id: string; name: string }[]>([]);
  const [selectedSubscriptions, setSelectedSubscriptions] = useState<string[]>([]);
  const [showSubDropdown, setShowSubDropdown] = useState(false);

  // Inventory v2 states
  const [invV2Summary, setInvV2Summary] = useState<InventoryV2Summary | null>(null);
  const [invV2Resources, setInvV2Resources] = useState<InventoryV2Resource[]>([]);
  const [invV2Total, setInvV2Total] = useState(0);
  const [invV2Page, setInvV2Page] = useState(1);
  const [invV2PageSize] = useState(50);
  const [invV2Loading, setInvV2Loading] = useState(false);
  const [invV2TagCompliance, setInvV2TagCompliance] = useState<TagComplianceMatrix | null>(null);
  const [invV2Search, setInvV2Search] = useState('');
  const [invV2TypeFilter, setInvV2TypeFilter] = useState('');
  const [invV2LocationFilter, setInvV2LocationFilter] = useState('');
  const [invV2EnvFilter, setInvV2EnvFilter] = useState('');
  const [invV2OnlyNonCompliant, setInvV2OnlyNonCompliant] = useState(false);
  const [invV2OnlyShadowIt, setInvV2OnlyShadowIt] = useState(false);
  const [invV2SelectedResource, setInvV2SelectedResource] = useState<InventoryV2Resource | null>(null);
  const [invV2DetailOpen, setInvV2DetailOpen] = useState(false);
  const [invV2Warnings, setInvV2Warnings] = useState<string[]>([]);
  const [invV2LastUpdated, setInvV2LastUpdated] = useState<string | null>(null);
  const [, setInvV2Subs] = useState<InventoryV2Sub[]>([]);

  // Sesion de Entra ID. Cuando la autenticacion esta desactivada (VITE_AZURE_AD_*
  // sin definir) arranca lista, de modo que el desarrollo local no cambia.
  const [sessionReady, setSessionReady] = useState(!authEnabled);
  const [authError, setAuthError] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const logConsoleEndRef = useRef<HTMLDivElement>(null);

  const fetchSubscriptions = async () => {
    try {
      const res = await apiFetch(`${API_URL}/api/subscriptions`);
      if (res.ok) {
        const data = await res.json();
        setSubscriptionsList(data);
        // By default, select all subscriptions if nothing is selected yet
        if (data.length > 0) {
          const ids = data.map((s: any) => s.id);
          setSelectedSubscriptions(ids);
        }
      }
    } catch {
      // Fallback fallback subscription mock
      const mockSubs = [
        { id: "00000000-0000-0000-0000-000000000001", name: "Demo Development" },
        { id: "00000000-0000-0000-0000-000000000002", name: "Demo Production" }
      ];
      setSubscriptionsList(mockSubs);
      setSelectedSubscriptions(mockSubs.map(s => s.id));
    }
  };

  // Initial load
  // Resuelve la sesion antes de pedir datos: el API responde 401 sin token
  // cuando corre con AUTH_ENABLED=true, asi que lanzar los fetch antes de tener
  // cuenta activa solo produce un panel vacio.
  useEffect(() => {
    if (!authEnabled) return;
    (async () => {
      try {
        const account = await initAuth();
        if (account) {
          setSessionReady(true);
        } else {
          await login(); // redirige a Entra ID y vuelve con la sesion resuelta
        }
      } catch (e) {
        setAuthError('No se pudo iniciar sesion con Microsoft Entra ID.');
        console.error(e);
      }
    })();
  }, []);

  useEffect(() => {
    if (!sessionReady) return;
    fetchSubscriptions();
    checkSyncStatus();
    fetchSnapshots();
    
    const interval = setInterval(() => {
      checkSyncStatus();
    }, 4000);
    return () => clearInterval(interval);
  }, [sessionReady]);

  // Reactively fetch all data whenever subscription selection changes
  useEffect(() => {
    if (!sessionReady) return;
    fetchStats();
    fetchFinopsReport();
    fetchSecopsReport();
    fetchRiskExposure();
    fetchIsoReport();
    fetchManualResources();
    fetchManualCreations();
    fetchTerraformCoverage();
    fetchHistory();
    setPage(1);
    // Inventory v2 data
    fetchInvV2Summary();
    fetchInvV2TagCompliance();
    setInvV2Page(1);
  }, [selectedSubscriptions, sessionReady]);

  // Inventory v2 resource fetching on filter/page changes
  useEffect(() => {
    if (activeTab === 'inventario' && sessionReady) {
      fetchInvV2Resources();
    }
  }, [sessionReady, invV2Page, invV2Search, invV2TypeFilter, invV2LocationFilter, invV2EnvFilter, invV2OnlyNonCompliant, invV2OnlyShadowIt, selectedSubscriptions]);

  useEffect(() => {
    if (!sessionReady) return;
    fetchInvV2Subs();
  }, [sessionReady]);

  // Reactively fetch resources whenever filters, query, page, or page size changes
  useEffect(() => {
    if (!sessionReady) return;
    fetchResources();
  }, [sessionReady, selectedSubscriptions, searchQuery, regionFilter, taggingFilter, page, pageSize]);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [inventoryHistory, finopsHistory, secopsHistory, k8sHistory,
      isInventoryTyping, isFinopsTyping, isSecopsTyping, isK8sTyping, consoleAgent, consoleOpen]);

  useEffect(() => {
    if (logConsoleEndRef.current) {
      logConsoleEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [syncLogs]);

  const fetchStats = async () => {
    try {
      const subsQuery = selectedSubscriptions.length > 0 ? `?subscriptions=${selectedSubscriptions.join(',')}` : '';
      const res = await apiFetch(`${API_URL}/api/stats${subsQuery}`);
      if (res.ok) {
        const data = await res.json();
        setStats(data);
        setIsBackendConnected(true);
      } else {
        throw new Error('Server error');
      }
    } catch {
      // Sin backend no se inventan cifras: se apaga el indicador y las tarjetas
      // quedan vacias. Antes se cargaba un juego de datos ficticios —494
      // recursos, 83.4% de cumplimiento, 133.60 USD de ahorro— que la interfaz
      // presentaba igual que los reales.
      setIsBackendConnected(false);
      setStats(null);
    }
  };

  const fetchTerraformCoverage = async () => {
    try {
      const res = await apiFetch(`${API_URL}/api/iac/terraform-coverage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subscriptionIds: selectedSubscriptions }),
      });
      if (res.ok) setTfCoverage(await res.json());
      else setTfCoverage(null);
    } catch {
      setTfCoverage(null);
    }
  };

  const fetchManualCreations = async () => {
    try {
      const res = await apiFetch(`${API_URL}/api/inventory/manual-creations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subscriptionIds: selectedSubscriptions }),
      });
      if (res.ok) setManualCreations(await res.json());
    } catch {
      setManualCreations(null);
    }
  };

  const fetchManualResources = async () => {
    try {
      const queryParams = new URLSearchParams();
      queryParams.append('provisioning', 'portal');
      queryParams.append('limit', '500');
      if (selectedSubscriptions.length > 0) queryParams.append('subscriptions', selectedSubscriptions.join(','));
      const res = await apiFetch(`${API_URL}/api/resources?${queryParams.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setManualResources(data);
      }
    } catch (e) {
      console.error("Error fetching manual resources:", e);
    }
  };



  const fetchSnapshots = async () => {
    setLoadingSnapshots(true);
    try {
      const res = await apiFetch(`${API_URL}/api/inventory/snapshots`);
      if (res.ok) {
        const data = await res.json();
        setSnapshots(data);
      }
    } catch (e) {
      console.error("Error fetching snapshots:", e);
    } finally {
      setLoadingSnapshots(false);
    }
  };

  const fetchFinopsReport = async () => {
    try {
      const subsQuery = selectedSubscriptions.length > 0 ? `?subscriptions=${selectedSubscriptions.join(',')}` : '';
      const res = await apiFetch(`${API_URL}/api/finops/report${subsQuery}`);
      if (res.ok) {
        const data = await res.json();
        setFinopsReport(data);
        return;
      }
    } catch { /* sin datos: la sección muestra su estado vacío */ }
    // Try legacy endpoint
    try {
      const res = await apiFetch(`${API_URL}/api/finops/details`);
      if (res.ok) {
        const data = await res.json();
        setFinopsReport({ ...data, orphaned_nics: [], empty_app_plans: [], old_snapshots: [], untagged_resources: [], resources_by_rg: [], estimated_savings_breakdown: {} });
        return;
      }
    } catch { /* sin datos: la sección muestra su estado vacío */ }
    // Igual que en SecOps: sin backend, sin cifras. El mock traia discos,
    // IPs y ahorros inventados que el panel mostraba como facturacion.
    setFinopsReport(null);
  };

  const fetchHistory = async () => {
    setHistoryLoading(true);
    try {
      const res = await apiFetch(`${API_URL}/api/inventory/history`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subscriptionIds: selectedSubscriptions, days: 90 }),
      });
      if (res.ok) setHistory(await res.json());
      else setHistory(null);
    } catch {
      setHistory(null);
    } finally {
      setHistoryLoading(false);
    }
  };

  const fetchRiskExposure = async () => {
    try {
      const subsQuery = selectedSubscriptions.length > 0 ? `?subscriptions=${selectedSubscriptions.join(',')}` : '';
      const res = await apiFetch(`${API_URL}/api/secops/exposure${subsQuery}`);
      if (res.ok) {
        setRiskExposure(await res.json());
        return;
      }
    } catch { /* sin datos: la sección muestra su estado vacío */ }
    setRiskExposure(null);
  };

  const fetchSecopsReport = async () => {
    try {
      const subsQuery = selectedSubscriptions.length > 0 ? `?subscriptions=${selectedSubscriptions.join(',')}` : '';
      const res = await apiFetch(`${API_URL}/api/secops/report${subsQuery}`);
      if (res.ok) {
        const data = await res.json();
        setSecopsReport(data);
        return;
      }
    } catch { /* sin datos: la sección muestra su estado vacío */ }
    try {
      const res = await apiFetch(`${API_URL}/api/secops/details`);
      if (res.ok) {
        const data = await res.json();
        setSecopsReport({ ...data, public_storage_accounts: [], exposed_keyvaults: [], public_ips_active: [], vms_without_encryption: [], attack_surface_summary: {} });
        return;
      }
    } catch { /* sin datos: la sección muestra su estado vacío */ }
    // Sin backend no se inventan hallazgos. Antes se cargaba un juego
    // ficticio —NSGs con nombres falsos, una IP pública inexistente— que el
    // panel presentaba igual que los reales: lo peor que puede hacer una
    // herramienta de seguridad es dar por auditado lo que no miró.
    setSecopsReport(null);
  };

  const fetchIsoReport = async () => {
    setLoadingIso(true);
    try {
      const res = await apiFetch(`${API_URL}/api/governance/iso`);
      if (res.ok) {
        const data = await res.json();
        setIsoReport(data);
      }
    } catch (e) {
      console.error("Error fetching ISO report:", e);
      // Fallback a mock en caso de offline
      setIsoReport({
        data: [
          {
            "name": "cluster-eastus2-dev",
            "resourceType": "AKS",
            "location": "eastus2",
            "resourceGroup": "aks-rg-dev",
            "subscription": "Demo Development",
            "Idtags": "Environment=Dev; Owner=platform",
            "Clasificación del activo": "Confidencial",
            "custodio": "platform",
            "confidencialidad": 3,
            "disponibilidad": 3,
            "integridad": 3,
            "puntuación del activo": 9,
            "Gestión de riesgo (SI/NO)": "SI"
          },
          {
            "name": "ststelladeveus2",
            "resourceType": "Storage",
            "location": "eastus2",
            "resourceGroup": "rg-cloudops-dev",
            "subscription": "Demo Development",
            "Idtags": "Environment=Dev; Owner=platform",
            "Clasificación del activo": "Restringido",
            "custodio": "platform",
            "confidencialidad": 2,
            "disponibilidad": 2,
            "integridad": 2,
            "puntuación del activo": 6,
            "Gestión de riesgo (SI/NO)": "NO"
          }
        ],
        stats: {
          total_assets: 2,
          classification_distribution: { "Confidencial": 1, "Restringido": 1 },
          risk_management_distribution: { "SI": 1, "NO": 1 },
          average_criticality_score: 7.5
        }
      });
    } finally {
      setLoadingIso(false);
    }
  };

  const fetchResources = async () => {
    try {
      const queryParams = new URLSearchParams();
      if (searchQuery) queryParams.append('query', searchQuery);
      if (regionFilter) queryParams.append('location', regionFilter);
      if (taggingFilter) queryParams.append('tagging_ok', taggingFilter);
      if (selectedSubscriptions.length > 0) queryParams.append('subscriptions', selectedSubscriptions.join(','));
      queryParams.append('page', page.toString());
      queryParams.append('page_size', pageSize.toString());
      
      const res = await apiFetch(`${API_URL}/api/resources?${queryParams.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setResources(data.data);
        setTotalResources(data.total);
      }
    } catch {
      setResources([]);
      setTotalResources(0);
    }
  };

  const handleExportCSV = () => {
    const nonCompliant = resources.filter(r => r.tagging_ok === "No");
    let csvContent = "data:text/csv;charset=utf-8,";
    csvContent += "Nombre,Tipo,Grupo de Recursos,Ubicacion,Suscripcion,Detalle de Cumplimiento\n";
    
    nonCompliant.forEach(r => {
      const typeStr = r.type ? r.type.split('/').pop() : "";
      csvContent += `"${r.name}","${typeStr}","${r.resourceGroup}","${r.location}","${r.subscription_name || 'Desarrollo'}","${r.tagging_details || 'Faltan tags'}"\n`;
    });
    
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `Reporte_Cumplimiento_Tags_Azure_${new Date().toISOString().split('T')[0]}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // --- Inventory v2 fetch functions ---
  const fetchInvV2Subs = async () => {
    try {
      const res = await apiFetch(`${API_URL}/api/inventory/subscriptions`);
      if (res.ok) {
        const data = await res.json();
        setInvV2Subs(data.subscriptions || []);
      }
    } catch (e) { console.warn('InvV2 subs fetch error', e); }
  };

  const fetchInvV2Summary = async () => {
    try {
      const res = await apiFetch(`${API_URL}/api/inventory/summary`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subscriptionIds: selectedSubscriptions })
      });
      if (res.ok) {
        const data = await res.json();
        setInvV2Summary(data);
        setInvV2Warnings(data.warnings || []);
        setInvV2LastUpdated(data.lastUpdated || null);
      }
    } catch (e) { console.warn('InvV2 summary error', e); }
  };

  const fetchInvV2TagCompliance = async () => {
    try {
      const res = await apiFetch(`${API_URL}/api/inventory/tag-compliance`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subscriptionIds: selectedSubscriptions })
      });
      if (res.ok) {
        const data = await res.json();
        setInvV2TagCompliance(data);
      }
    } catch (e) { console.warn('InvV2 tag compliance error', e); }
  };

  const fetchInvV2Resources = async (pageOverride?: number) => {
    setInvV2Loading(true);
    try {
      const res = await apiFetch(`${API_URL}/api/inventory/resources`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subscriptionIds: selectedSubscriptions,
          filters: {
            search: invV2Search,
            types: invV2TypeFilter ? [invV2TypeFilter] : [],
            locations: invV2LocationFilter ? [invV2LocationFilter] : [],
            environments: invV2EnvFilter ? [invV2EnvFilter] : [],
            onlyNonCompliant: invV2OnlyNonCompliant,
            onlyShadowItCandidates: invV2OnlyShadowIt
          },
          page: pageOverride || invV2Page,
          pageSize: invV2PageSize
        })
      });
      if (res.ok) {
        const data = await res.json();
        setInvV2Resources(data.items || []);
        setInvV2Total(data.total || 0);
        if (data.warnings?.length) setInvV2Warnings(prev => [...prev, ...data.warnings]);
      }
    } catch (e) { console.warn('InvV2 resources error', e); }
    setInvV2Loading(false);
  };

  const handleInvV2ExportCSV = async () => {
    try {
      const res = await apiFetch(`${API_URL}/api/inventory/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subscriptionIds: selectedSubscriptions,
          filters: {
            search: invV2Search,
            onlyNonCompliant: invV2OnlyNonCompliant,
            onlyShadowItCandidates: invV2OnlyShadowIt
          }
        })
      });
      if (res.ok) {
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `Inventario_Gobernanza_${new Date().toISOString().split('T')[0]}.csv`;
        a.click();
        window.URL.revokeObjectURL(url);
        showToast('CSV exportado exitosamente', 'success');
      }
    } catch { showToast('Error al exportar CSV', 'error'); }
  };

  const copyToClipboard = (text: string, label: string = 'Valor') => {
    navigator.clipboard.writeText(text);
    setShowCopyNotification(true);
    showToast(`${label} copiado al portapapeles`, 'success');
    setTimeout(() => setShowCopyNotification(false), 2000);
  };


  // Reset page when filters change
  useEffect(() => {
    setPage(1);
  }, [searchQuery, regionFilter, taggingFilter]);

  // La consola se sintoniza con la sección en la que se está trabajando.
  useEffect(() => {
    const porPestana: Partial<Record<string, AgentType>> = {
      inventario: 'inventory', finops: 'finops', secops: 'secops',
      iac: 'inventory', iso: 'inventory', k8s: 'k8s',
    };
    const agente = porPestana[activeTab];
    if (agente) setConsoleAgent(agente);
  }, [activeTab]);

  const checkSyncStatus = async () => {
    try {
      const res = await apiFetch(`${API_URL}/api/sync/status`);
      if (res.ok) {
        const data = await res.json();
        if (syncRunning && !data.running) {
          fetchStats();
          fetchResources();
          fetchSnapshots();
        }
        setSyncRunning(data.running);
        setSyncLogs(data.logs);
      }
    } catch {
      // Offline mode
    }
  };

  /**
   * Abre la consola en el agente indicado y, si se pasa texto, lo envia.
   *
   * Es el punto por el que entran los botones de las tablas ("Analizar",
   * "Remediar"): antes escribian en un chat que podia estar en otra pestaña,
   * de modo que la respuesta llegaba a un panel que el usuario no estaba
   * mirando.
   */
  const askAgent = (agentType: AgentType, text?: string) => {
    setConsoleAgent(agentType);
    setConsoleOpen(true);
    if (text) handleSendAgentMessage(agentType, text);
  };

  const handleSendAgentMessage = async (agentType: AgentType, textOverride?: string) => {
    const text = textOverride || (agentType === 'inventory' ? inventoryInput : agentType === 'finops' ? finopsInput : agentType === 'k8s' ? k8sInput : secopsInput);
    if (!text.trim()) return;

    const setInput = agentType === 'inventory' ? setInventoryInput : agentType === 'finops' ? setFinopsInput : agentType === 'k8s' ? setK8sInput : setSecopsInput;
    const setHistory = agentType === 'inventory' ? setInventoryHistory : agentType === 'finops' ? setFinopsHistory : agentType === 'k8s' ? setK8sHistory : setSecopsHistory;
    const setIsTyping = agentType === 'inventory' ? setIsInventoryTyping : agentType === 'finops' ? setIsFinopsTyping : agentType === 'k8s' ? setIsK8sTyping : setIsSecopsTyping;

    const userMsg: ChatMessage = {
      id: Math.random().toString(),
      sender: 'user',
      text: text,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setHistory(prev => [...prev, userMsg]);
    setInput('');
    setIsTyping(true);

    try {
      const res = agentType === 'k8s'
        ? await apiFetch(`${API_URL}/api/k8s/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text })
          })
        : await apiFetch(`${API_URL}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
              message: text, 
              agent_type: agentType,
              subscriptions: selectedSubscriptions 
            })
          });

      if (res.ok) {
        const data = await res.json();
        setHistory(prev => [...prev, {
          id: Math.random().toString(),
          sender: 'bot',
          text: data.answer,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          mode: data.mode
        }]);
      } else {
        throw new Error('Failed chat');
      }
    } catch {
      setTimeout(() => {
        const mockReply = processMockQuestion(text, agentType);
        setHistory(prev => [...prev, {
          id: Math.random().toString(),
          sender: 'bot',
          text: mockReply,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          mode: 'offline'
        }]);
      }, 850);
    } finally {
      setIsTyping(false);
    }
  };

  const processMockQuestion = (question: string, agentType: string): string => {
    const q = question.toLowerCase();
    if (agentType === 'k8s') {
      return "### ☸️ Agente SRE Kubernetes (sin conexión)\n\nNo pude alcanzar el API del clúster. Verifica que el backend tenga definidas `K8S_CLUSTER_NAME`, `K8S_RESOURCE_GROUP` y `K8S_SUBSCRIPTION_ID`, y que el Service Principal tenga permiso para ejecutar Run Command sobre el clúster.";
    }
    if (agentType === 'finops') {
      if (q.includes('ahorro') || q.includes('huérfano') || q.includes('costo') || q.includes('disco') || q.includes('ip')) {
        return "### 💰 Reporte de Ahorros Estimados (FinOps Local Mock)\n\n• **Ahorro Mensual Total:** `$133.60 USD`\n\n#### 📌 Recursos sugeridos para eliminar:\n1. **`vm-dev-db-01-temp-disk`** (14 discos SSD huérfanos) - Ahorro estimado: `$112.00 USD/mes`.\n2. **IPs Públicas sin usar** (6 IPs) - Ahorro estimado: `$21.60 USD/mes`.\n3. **22 Interfaces de red inactivas** - Ahorro: Liberación de IPs privadas del espacio de red.\n\n*Recomendación: Procede a eliminar los discos sin asociar y desasocia las IPs públicas desde el Portal de Azure.*";
      }
      return "### 💰 Asistente de FinOps\n\nHola, puedo ayudarte a analizar costos de tu suscripción de desarrollo. Pregúntame por ejemplo cuáles discos están huérfanos o cuánto dinero podemos ahorrar este mes.";
    } else if (agentType === 'secops') {
      if (q.includes('puerto') || q.includes('seguridad') || q.includes('nsg') || q.includes('fallado') || q.includes('failed')) {
        return "### 🛡️ Reporte de Vulnerabilidades & Salud (SecOps Local Mock)\n\n• **Exposición Crítica:** `4 NSGs` tienen puertos de administración abiertos al público.\n• **Recursos Fallidos:** `1 recurso` en estado de aprovisionamiento fallido.\n\n#### ⚠️ NSGs Vulnerables:\n- **`nsg-dev-web`** en RG: `rg-plataforma-dev` permite acceso al puerto **22 (SSH)** desde `0.0.0.0/0`.\n- **`nsg-dev-db`** en RG: `rg-plataforma-dev` permite acceso al puerto **3389 (RDP)** desde `*`.\n\n*Recomendación: Restringe las reglas entrantes de estos NSGs a la IP corporativa para mitigar riesgos de intrusión.*";
      }
      return "### 🛡️ Asistente de SecOps\n\nHola, realizo análisis de seguridad en tiempo real. Pregúntame sobre puertos abiertos a internet pública o sobre recursos en estado fallido.";
    } else { // inventory
      if (q.includes('tag') || q.includes('política') || q.includes('incumple') || q.includes('cumplimiento')) {
        return "### 📋 Reporte de Gobernanza de Tags (Local Mock)\n\nEl cumplimiento global de tagging en **la suscripción de demostración** es del **83.4%**.\n\n• Recursos **no cumplidores**: `82` recursos\n\n#### ⚠️ Muestra de recursos con tags faltantes:\n1. `vm-dev-db-01` | RG: `rg-plataforma-dev` | **Faltan: Customer, Platform, Suite**\n2. `sql-dev-srv-02` | RG: `rg-plataforma-dev` | **Faltan: Customer, Tenant, Platform, Product, Suite**\n\n*Sugerencia: Haz clic en 'Preguntar a IA' en la tabla de recursos para generar una consulta específica para cada recurso.*";
      }
      return "### 📊 Resumen del Inventario Azure (Local Mock)\n\n• **Recursos Azure Totales:** `494` recursos.\n• **Tags Completos (6/6):** `412` recursos.\n• **Recursos sin Tags Obligatorios:** `82` recursos.\n• **Cumplimiento Global de Gobernanza:** `83.4%`.\n\n*Nota: Estos datos provienen del inventario en tiempo real de tu suscripción de desarrollo.*";
    }
  };

  const handleSync = async () => {
    try {
      setShowSyncModal(true);
      setSyncLogs('Enviando solicitud de sincronización...\n');
      const res = await apiFetch(`${API_URL}/api/sync`, { method: 'POST' });
      if (res.ok) {
        setSyncRunning(true);
      }
    } catch {
      setSyncLogs(prev => prev + '\n❌ Error al conectar con el servidor para iniciar la sincronización. Asegúrate de que el backend FastAPI esté ejecutándose en http://localhost:8000\n');
    }
  };

  const handleGenerateIaC = async (resource: Resource) => {
    setSelectedResourceForIaC(resource);
    setIacGenerating(true);
    setIacModalOpen(true);
    setGeneratedIaCFiles(null);
    setActiveIaCFileTab('main_tf');
    
    // Guess environment and domain dynamically based on resource type & subscription
    let guessedEnv: 'dev' | 'qa' | 'prod' = 'dev';
    const subName = (resource.subscription_name || '').toLowerCase();
    const rgName = (resource.resourceGroup || '').toLowerCase();
    if (subName.includes('prod') || rgName.includes('prod')) {
      guessedEnv = 'prod';
    } else if (subName.includes('qa') || rgName.includes('qa')) {
      guessedEnv = 'qa';
    }
    setIacEnvironment(guessedEnv);

    let guessedDomain: 'networking' | 'platform' | 'data' | 'security' = 'platform';
    const typeLower = (resource.type || '').toLowerCase();
    if (typeLower.includes('network') || typeLower.includes('route') || typeLower.includes('pip') || typeLower.includes('nic') || typeLower.includes('nsg')) {
      guessedDomain = 'networking';
    } else if (typeLower.includes('sql') || typeLower.includes('database') || typeLower.includes('storage') || typeLower.includes('cosmos')) {
      guessedDomain = 'data';
    } else if (typeLower.includes('vault') || typeLower.includes('security') || typeLower.includes('policy')) {
      guessedDomain = 'security';
    }
    setIacDomain(guessedDomain);

    try {
      const azureId = resource.id || `/subscriptions/${selectedSubscriptions[0] || PLACEHOLDER_SUBSCRIPTION}/resourceGroups/${resource.resourceGroup}/providers/${resource.type}/${resource.name}`;
      
      const res = await apiFetch(`${API_URL}/api/iac/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          resource_id: azureId,
          environment: guessedEnv,
          domain: guessedDomain
        })
      });

      if (res.ok) {
        const data = await res.json();
        setGeneratedIaCFiles(data);
      } else {
        console.error('Failed to generate HCL');
      }
    } catch (e) {
      console.error('Error generating HCL:', e);
    } finally {
      setIacGenerating(false);
    }
  };

  const handleRegenerateIaC = async (env: 'dev' | 'qa' | 'prod', dom: 'networking' | 'platform' | 'data' | 'security') => {
    if (!selectedResourceForIaC) return;
    setIacGenerating(true);
    setIacEnvironment(env);
    setIacDomain(dom);
    try {
      const azureId = selectedResourceForIaC.id || `/subscriptions/${selectedSubscriptions[0] || PLACEHOLDER_SUBSCRIPTION}/resourceGroups/${selectedResourceForIaC.resourceGroup}/providers/${selectedResourceForIaC.type}/${selectedResourceForIaC.name}`;
      const res = await apiFetch(`${API_URL}/api/iac/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          resource_id: azureId,
          environment: env,
          domain: dom
        })
      });

      if (res.ok) {
        const data = await res.json();
        setGeneratedIaCFiles(data);
      }
    } catch (e) {
      console.error('Error regenerating HCL:', e);
    } finally {
      setIacGenerating(false);
    }
  };

  // copyToClipboard is defined in the inventory v2 section above (line ~735)



  // Simple custom Markdown rendering helper
  const parseMarkdown = (text: string) => {
    const lines = text.split('\n');
    const elements: React.ReactNode[] = [];
    let listItems: React.ReactNode[] = [];
    let tableRows: React.ReactNode[] = [];
    let insideTable = false;
    let tableHeaders: string[] = [];

    const flushList = (key: string) => {
      if (listItems.length > 0) {
        elements.push(<ul key={`list-${key}`}>{...listItems}</ul>);
        listItems = [];
      }
    };

    const flushTable = (key: string) => {
      if (tableRows.length > 0) {
        elements.push(
          <div className="custom-table-container" key={`table-wrapper-${key}`} style={{margin: '10px 0'}}>
            <table className="custom-table">
              <thead>
                <tr>
                  {tableHeaders.map((h, i) => <th key={i}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {...tableRows}
              </tbody>
            </table>
          </div>
        );
        tableRows = [];
        tableHeaders = [];
        insideTable = false;
      }
    };

    const processText = (textSegment: string) => {
      // Process bold **
      const boldRegex = /\*\*(.*?)\*\*/g;
      const codeRegex = /`(.*?)`/g;
      const parts: React.ReactNode[] = [];
      
      // Handle inline code first or bold
      // This is a quick and dirty parser for presentation
      const matches: {type: 'bold' | 'code', index: number, length: number, content: string}[] = [];
      
      let m;
      while ((m = boldRegex.exec(textSegment)) !== null) {
        matches.push({type: 'bold', index: m.index, length: m[0].length, content: m[1]});
      }
      
      boldRegex.lastIndex = 0; // reset
      
      while ((m = codeRegex.exec(textSegment)) !== null) {
        matches.push({type: 'code', index: m.index, length: m[0].length, content: m[1]});
      }
      codeRegex.lastIndex = 0; // reset
      
      // Sort matches by index
      matches.sort((a, b) => a.index - b.index);
      
      let lastIndex = 0;
      matches.forEach((match, idx) => {
        if (match.index >= lastIndex) {
          // Add preceding plain text
          if (match.index > lastIndex) {
            parts.push(textSegment.substring(lastIndex, match.index));
          }
          // Add formatted text
          if (match.type === 'bold') {
            parts.push(<strong key={idx}>{match.content}</strong>);
          } else {
            parts.push(<code key={idx}>{match.content}</code>);
          }
          lastIndex = match.index + match.length;
        }
      });
      
      if (lastIndex < textSegment.length) {
        parts.push(textSegment.substring(lastIndex));
      }
      
      return parts.length > 0 ? parts : textSegment;
    };

    lines.forEach((line, index) => {
      // Table processing
      if (line.trim().startsWith('|')) {
        flushList(`before-table-${index}`);
        const cells = line.split('|').map(c => c.trim()).filter((_, i, arr) => i > 0 && i < arr.length - 1);
        
        if (line.includes('---')) {
          // separator line, skip
          return;
        }
        
        if (!insideTable) {
          insideTable = true;
          tableHeaders = cells;
        } else {
          tableRows.push(
            <tr key={`tr-${index}`}>
              {cells.map((c, cellIdx) => <td key={cellIdx}>{processText(c)}</td>)}
            </tr>
          );
        }
        return;
      } else {
        flushTable(`before-other-${index}`);
      }

      // List processing
      if (line.trim().startsWith('- ') || line.trim().startsWith('• ')) {
        const cleanLine = line.trim().replace(/^[-•]\s+/, '');
        listItems.push(<li key={`li-${index}`}>{processText(cleanLine)}</li>);
        return;
      } else {
        flushList(`before-header-${index}`);
      }

      // Header processing
      if (line.startsWith('### ')) {
        elements.push(<h3 key={index}>{processText(line.replace('### ', ''))}</h3>);
      } else if (line.startsWith('## ')) {
        elements.push(<h2 key={index}>{processText(line.replace('## ', ''))}</h2>);
      } else if (line.startsWith('# ')) {
        elements.push(<h1 key={index}>{processText(line.replace('# ', ''))}</h1>);
      } else if (line.trim() === '') {
        elements.push(<div key={index} style={{height: '8px'}} />);
      } else {
        elements.push(<p key={index}>{processText(line)}</p>);
      }
    });

    flushList('final');
    flushTable('final');
    return elements;
  };

  const renderAgentChat = (agentType: AgentType) => {
    const history = agentType === 'inventory' ? inventoryHistory : agentType === 'finops' ? finopsHistory : agentType === 'k8s' ? k8sHistory : secopsHistory;
    const inputVal = agentType === 'inventory' ? inventoryInput : agentType === 'finops' ? finopsInput : agentType === 'k8s' ? k8sInput : secopsInput;
    const setInput = agentType === 'inventory' ? setInventoryInput : agentType === 'finops' ? setFinopsInput : setSetChatInputHelper(agentType);
    const isTyping = agentType === 'inventory' ? isInventoryTyping : agentType === 'finops' ? isFinopsTyping : agentType === 'k8s' ? isK8sTyping : isSecopsTyping;
    const agentName = agentType === 'inventory' ? 'Agente Inventario' : agentType === 'finops' ? 'Agente FinOps' : agentType === 'k8s' ? 'Agente K8s SRE' : 'Agente SecOps';
    const placeholder = agentType === 'inventory' ? 'Consulta recursos o tags...' : agentType === 'finops' ? 'Pregunta sobre costos y ahorros...' : agentType === 'k8s' ? 'Pregunta por pods, nodos o incidencias del clúster...' : 'Consulta seguridad o recursos fallidos...';

    const suggestions = agentType === 'k8s'
      ? [
          { text: "Hazme un diagnóstico rápido del clúster", label: "Diagnóstico" },
          { text: "¿Qué pods están en CrashLoopBackOff u OOMKilled?", label: "Pods con problemas" }
        ]
      : agentType === 'inventory' 
      ? [
          { text: "¿Qué recursos no cumplen con la política de tags?", label: "No cumplidores" },
          { text: "¿Qué recursos están en el grupo de recursos rg-plataforma-dev?", label: "Recursos en RG" }
        ]
      : agentType === 'finops'
      ? [
          { text: "¿Cuáles son las oportunidades de ahorro en mi suscripción?", label: "Oportunidades de ahorro" },
          { text: "Muéstrame la lista de discos duros sin asociar (unattached)", label: "Discos huérfanos" }
        ]
      : [
          { text: "¿Qué NSGs tienen puertos expuestos a Internet?", label: "NSGs Expuestos" },
          { text: "¿Cuáles recursos están en estado de aprovisionamiento fallido?", label: "Recursos Fallidos" }
        ];

    return (
      <div className="teams-chat-area" style={{ height: '100%', display: 'flex', flexDirection: 'column', border: 'none', background: 'transparent' }}>
        {/* Chat Header */}
        <div className="teams-chat-header" style={{ padding: '12px 16px', background: 'rgba(255,255,255,0.02)', borderBottom: '1px solid rgba(255,255,255,0.06)', borderRadius: '12px 12px 0 0' }}>
          <div className="teams-bot-info">
            <div className="teams-bot-avatar" style={{ fontSize: '1.1rem' }}>
              {agentType === 'inventory' ? '📋' : agentType === 'finops' ? '💰' : agentType === 'k8s' ? '☸️' : '🛡️'}
            </div>
            <div className="teams-bot-details">
              <h3 style={{ fontSize: '0.875rem' }}>{agentName}</h3>
              <div className="teams-bot-status">
                <span className="dot dot-success" style={{ width: '6px', height: '6px' }}></span>
                <span style={{ fontSize: '0.7rem' }}>Agente Activo</span>
              </div>
            </div>
          </div>
        </div>

        {/* Chat Messages */}
        <div className="teams-chat-messages" style={{ flex: 1, padding: '16px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '12px', minHeight: '380px', maxHeight: '500px' }}>
          {history.map((msg) => (
            <div key={msg.id} className={`teams-message-row ${msg.sender === 'user' ? 'user-message' : 'bot-message'}`} style={{ margin: 0 }}>
              <div className="message-bubble-container" style={{ maxWidth: '90%' }}>
                <div className="message-meta" style={{ fontSize: '0.65rem', marginBottom: '2px' }}>
                  <span style={{ fontWeight: '600', marginRight: '6px', color: '#E1E1E1' }}>
                    {msg.sender === 'user' ? USER_NAME : agentName}
                  </span>
                  <span>{msg.timestamp}</span>
                </div>
                <div className="message-bubble" style={{ padding: '8px 12px', fontSize: '0.8rem', borderRadius: '8px' }}>
                  {msg.sender === 'bot' ? parseMarkdown(msg.text) : msg.text}
                  {msg.mode && msg.mode.includes('offline') && (
                    <div style={{ fontSize: '0.65rem', color: 'var(--warning)', marginTop: '4px', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '2px' }}>
                      Offline Engine
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
          {isTyping && (
            <div className="teams-message-row bot-message" style={{ margin: 0 }}>
              <div className="message-bubble-container">
                <div className="message-bubble" style={{ padding: '6px 12px', minWidth: '45px', borderRadius: '8px' }}>
                  <div className="typing-indicator" style={{ gap: '3px' }}>
                    <span className="typing-dot" style={{ width: '5px', height: '5px' }}></span>
                    <span className="typing-dot" style={{ width: '5px', height: '5px' }}></span>
                    <span className="typing-dot" style={{ width: '5px', height: '5px' }}></span>
                  </div>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Suggestions & Input */}
        <div className="teams-chat-input-container" style={{ padding: '12px', background: 'rgba(255,255,255,0.01)', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
          <div className="chat-suggestions" style={{ marginBottom: '8px', display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            {suggestions.map((sug, idx) => (
              <span 
                key={idx}
                className="suggestion-chip"
                style={{ fontSize: '0.7rem', padding: '4px 8px', borderRadius: '4px', cursor: 'pointer' }}
                onClick={() => handleSendAgentMessage(agentType, sug.text)}
              >
                {sug.label}
              </span>
            ))}
          </div>

          <form 
            className="teams-input-box"
            style={{ borderRadius: '6px', padding: '4px 8px' }}
            onSubmit={(e) => {
              e.preventDefault();
              handleSendAgentMessage(agentType);
            }}
          >
            <input 
              type="text" 
              className="teams-input"
              style={{ fontSize: '0.8rem', padding: '6px 0' }}
              placeholder={placeholder}
              value={inputVal}
              onChange={(e) => setInput(e.target.value)}
            />
            <div className="teams-input-actions">
              <button 
                type="submit" 
                className={`teams-send-btn ${inputVal.trim() ? 'active' : ''}`}
                style={{ width: '26px', height: '26px' }}
                disabled={!inputVal.trim()}
              >
                <Send size={12} />
              </button>
            </div>
          </form>
        </div>
      </div>
    );
  };

  const setSetChatInputHelper = (agentType: AgentType) => {
    return (val: string) => {
      if (agentType === 'inventory') setInventoryInput(val);
      else if (agentType === 'finops') setFinopsInput(val);
      else if (agentType === 'k8s') setK8sInput(val);
      else setSecopsInput(val);
    };
  };

  if (!sessionReady) {
    return (
      <div className="app-container" style={{ display: 'grid', placeItems: 'center' }}>
        <div style={{ textAlign: 'center', opacity: 0.85 }}>
          <div className="logo-icon" style={{ margin: '0 auto 16px' }}>AI</div>
          <p>{authError ?? 'Iniciando sesion con Microsoft Entra ID...'}</p>
          {authError && (
            <button className="btn btn-primary" onClick={() => login()} style={{ marginTop: 12 }}>
              Reintentar
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="app-container">
      {/* Sidebar Navigation */}
      <aside className="app-sidebar">
        <div className="sidebar-logo">
          <div className="logo-icon">AI</div>
          <div className="logo-text">DevOps Agents</div>
        </div>

        <nav className="sidebar-nav">
          <div 
            className={`nav-item ${activeTab === 'inventario' ? 'active' : ''}`}
            onClick={() => setActiveTab('inventario')}
          >
            <LayoutDashboard size={18} />
            Inventario & Tags
          </div>
          <div 
            className={`nav-item ${activeTab === 'finops' ? 'active' : ''}`}
            onClick={() => setActiveTab('finops')}
          >
            <Database size={18} />
            Agente FinOps (Costos)
          </div>
          <div 
            className={`nav-item ${activeTab === 'secops' ? 'active' : ''}`}
            onClick={() => setActiveTab('secops')}
          >
            <Shield size={18} />
            Agente SecOps & Salud
          </div>
          <div 
            className={`nav-item ${activeTab === 'iac' ? 'active' : ''}`}
            onClick={() => setActiveTab('iac')}
          >
            <Terminal size={18} />
            IaC & Terraform
          </div>
          <div 
            className={`nav-item ${activeTab === 'iso' ? 'active' : ''}`}
            onClick={() => setActiveTab('iso')}
          >
            <FileText size={18} />
            Gobernanza ISO 27001
          </div>
          {/* Kubernetes no tiene sección propia: su pestaña solo contenía un
              chat, y los cuatro agentes viven ahora en la consola lateral. */}
          <button
            className="nav-item nav-item-action"
            onClick={() => { setConsoleAgent('k8s'); setConsoleOpen(true); }}
          >
            <Layers size={18} />
            Agente SRE Kubernetes
          </button>

        </nav>

        <div className="sidebar-footer">
          <div className="footer-user">
            <div className="avatar-user">{USER_INITIALS}</div>
            <div className="user-info">
              <span className="user-name">{USER_NAME}</span>
              <span className="user-role">{USER_ROLE}</span>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="app-content">
        <header className="content-header">
          <div className="header-title-container">
            <h1>
              {activeTab === 'inventario' && 'Inventario Cloud & Gobernanza de Tags'}
              {activeTab === 'finops' && 'Agente FinOps & Optimización de Costos'}
              {activeTab === 'secops' && 'Agente SecOps & Salud de Suscripciones'}
              {activeTab === 'iac' && 'Módulo de Infraestructura como Código & Terraform'}
              {activeTab === 'iso' && 'Gobernanza de Activos & Cumplimiento ISO 27001'}
            </h1>
            <p>
              {activeTab === 'inventario' && 'Métricas de cumplimiento y auditoría de etiquetas de Azure en tiempo real.'}
              {activeTab === 'finops' && 'Identificación de recursos huérfanos, IPs públicas libres y ahorro potencial.'}
              {activeTab === 'secops' && 'Vulnerabilidades en puertos de red expuestos y diagnóstico de salud operativa.'}
              {activeTab === 'iac' && 'Generación inteligente de HCL de Terraform, importación declarativa y control de Shadow IT.'}
              {activeTab === 'iso' && 'Clasificación de seguridad (C-I-D), puntuación de criticidad y gestión de riesgos conforme a normativa ISO 27001.'}
            </p>
          </div>

          <div className="header-actions">
            <button
              className="btn btn-secondary"
              onClick={() => setConsoleOpen((v) => !v)}
              style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
              title="Consola de agentes"
            >
              <MessageSquare size={14} />
              Agentes
            </button>

            {/* Health status indicator */}
            <div className={`badge ${isBackendConnected ? 'badge-success' : 'badge-warning'}`} style={{ gap: '6px' }}>
              <span className={`dot ${isBackendConnected ? 'dot-success' : 'dot-warning'}`}></span>
              {isBackendConnected ? 'API Conectada' : 'Simulación (API Offline)'}
            </div>

            {/* Selector de Suscripciones Global */}
            <div style={{ position: 'relative' }}>
              <button 
                className="btn btn-secondary"
                onClick={() => setShowSubDropdown(!showSubDropdown)}
                style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 14px' }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/></svg>
                <span>Suscripciones ({selectedSubscriptions.length})</span>
                <span style={{ fontSize: '0.6rem', transition: 'transform 0.2s', transform: showSubDropdown ? 'rotate(180deg)' : 'rotate(0)' }}>▼</span>
              </button>

              {showSubDropdown && (
                <div className="glass animate-fade-in" style={{
                  position: 'absolute',
                  top: '100%',
                  right: 0,
                  marginTop: '8px',
                  width: '280px',
                  background: 'rgba(15, 23, 42, 0.95)',
                  border: '1px solid rgba(255,255,255,0.08)',
                  borderRadius: '12px',
                  padding: '12px',
                  zIndex: 9999,
                  boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.4), 0 8px 10px -6px rgba(0, 0, 0, 0.4)'
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '8px', marginBottom: '8px' }}>
                    <span style={{ fontSize: '0.75rem', fontWeight: '700', color: '#fff' }}>Filtrar por Suscripción</span>
                    <div style={{ display: 'flex', gap: '6px' }}>
                      <span 
                        onClick={() => setSelectedSubscriptions(subscriptionsList.map(s => s.id))}
                        style={{ fontSize: '0.65rem', color: 'var(--primary)', cursor: 'pointer', fontWeight: '600' }}
                      >
                        Todas
                      </span>
                      <span style={{ fontSize: '0.65rem', color: 'var(--text-secondary)' }}>|</span>
                      <span 
                        onClick={() => setSelectedSubscriptions([])}
                        style={{ fontSize: '0.65rem', color: '#f43f5e', cursor: 'pointer', fontWeight: '600' }}
                      >
                        Ninguna
                      </span>
                    </div>
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '180px', overflowY: 'auto' }}>
                    {subscriptionsList.map(sub => {
                      const isChecked = selectedSubscriptions.includes(sub.id);
                      return (
                        <label 
                          key={sub.id} 
                          style={{ 
                            display: 'flex', 
                            alignItems: 'center', 
                            gap: '8px', 
                            cursor: 'pointer', 
                            padding: '6px 8px', 
                            borderRadius: '6px',
                            background: isChecked ? 'rgba(99, 102, 241, 0.08)' : 'transparent',
                            transition: 'background 0.2s'
                          }}
                        >
                          <input 
                            type="checkbox" 
                            checked={isChecked}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedSubscriptions([...selectedSubscriptions, sub.id]);
                              } else {
                                setSelectedSubscriptions(selectedSubscriptions.filter(id => id !== sub.id));
                              }
                            }}
                            style={{ 
                              cursor: 'pointer',
                              accentColor: 'var(--primary)'
                            }}
                          />
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '1px', overflow: 'hidden' }}>
                            <span style={{ fontSize: '0.72rem', fontWeight: '600', color: isChecked ? '#fff' : 'var(--text-secondary)', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap', maxWidth: '210px' }}>
                              {sub.name}
                            </span>
                            <span style={{ fontSize: '0.6rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
                              {sub.id.substring(0, 8)}...
                            </span>
                          </div>
                        </label>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>

            <button 
              className={`btn ${syncRunning ? 'btn-syncing' : 'btn-secondary'}`}
              onClick={handleSync}
              disabled={syncRunning}
            >
              <RefreshCw size={14} className={syncRunning ? 'pulse' : ''} />
              {syncRunning ? 'Sincronizando...' : 'Sincronizar Inventario'}
            </button>
          </div>
        </header>

        {/* Dashboard Body */}
        <div className="content-body">
          
          {/* Active View: Inventario & Tags */}
          {activeTab === 'inventario' && (
            <SectionBoundary name="Inventario y gobernanza">
            <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

                {/* Warnings Banner */}
                {invV2Warnings.length > 0 && (
                  <div style={{ background: 'rgba(245, 158, 11, 0.1)', border: '1px solid rgba(245, 158, 11, 0.3)', borderRadius: '10px', padding: '12px 16px', display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <AlertTriangle size={18} color="#f59e0b" />
                    <div style={{ fontSize: '0.85rem', color: '#f59e0b' }}>
                      {invV2Warnings.map((w, i) => <div key={i}>{w}</div>)}
                    </div>
                    <button onClick={() => setInvV2Warnings([])} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: '#f59e0b', cursor: 'pointer' }}><X size={16} /></button>
                  </div>
                )}

                {/* KPI Grid - 5 Columns */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '12px' }}>
                  <div className="stat-card glass">
                    <div className="stat-icon" style={{ backgroundColor: 'rgba(99, 102, 241, 0.15)', color: 'var(--primary)' }}><Database size={20} /></div>
                    <div className="stat-value">{(invV2Summary?.totalResources || stats?.total_resources || 0).toLocaleString()}</div>
                    <div className="stat-label">Recursos Totales</div>
                  </div>
                  <div className="stat-card glass">
                    <div className="stat-icon" style={{ backgroundColor: 'rgba(16, 185, 129, 0.15)', color: 'var(--success)' }}><CheckCircle size={20} /></div>
                    <div className="stat-value">{invV2Summary?.tagCompliancePercentage?.toFixed(1) || stats?.tag_compliance_percentage || 0}%</div>
                    <div className="stat-label">Cumplimiento de Tags</div>
                  </div>
                  <div className="stat-card glass">
                    <div className="stat-icon" style={{ backgroundColor: 'rgba(244, 63, 94, 0.15)', color: '#f43f5e' }}><AlertTriangle size={20} /></div>
                    <div className="stat-value">{(invV2Summary?.nonCompliantResources || 0).toLocaleString()}</div>
                    <div className="stat-label">Sin Tags Completos</div>
                  </div>
                  <div className="stat-card glass">
                    <div className="stat-icon" style={{ backgroundColor: 'rgba(168, 85, 247, 0.15)', color: '#a855f7' }}><Layers size={20} /></div>
                    <div className="stat-value">{(invV2Summary?.shadowItCandidates || 0).toLocaleString()}</div>
                    <div
                      className="stat-label"
                      title="Sin marca de IaC, sin custodio, con tags obligatorias incompletas y sin ser un recurso derivado de otro. Las cuatro condiciones a la vez."
                      style={{ cursor: 'help' }}
                    >
                      Candidatos Shadow IT
                    </div>
                  </div>
                  <div className="stat-card glass">
                    <div className="stat-icon" style={{ backgroundColor: 'rgba(14, 165, 233, 0.15)', color: '#0ea5e9' }}><Globe size={20} /></div>
                    <div className="stat-value">{invV2Summary?.totalRegions || 0}</div>
                    <div className="stat-label">Regiones Activas</div>
                  </div>
                </div>

                {/* Secondary KPIs Row */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '14px' }}>
                  <div className="glass" style={{ padding: '14px 18px', borderRadius: '12px', display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{ width: '40px', height: '40px', borderRadius: '10px', background: 'rgba(34, 197, 94, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#22c55e' }}><Users size={18} /></div>
                    <div><div style={{ fontSize: '1.3rem', fontWeight: '700', color: '#fff' }}>{invV2Summary?.totalSubscriptions || 0}</div><div style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.5)' }}>Suscripciones</div></div>
                  </div>
                  <div className="glass" style={{ padding: '14px 18px', borderRadius: '12px', display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{ width: '40px', height: '40px', borderRadius: '10px', background: 'rgba(251, 146, 60, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fb923c' }}><Layers size={18} /></div>
                    <div><div style={{ fontSize: '1.3rem', fontWeight: '700', color: '#fff' }}>{invV2Summary?.totalResourceGroups || 0}</div><div style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.5)' }}>Resource Groups</div></div>
                  </div>
                  <div className="glass" style={{ padding: '14px 18px', borderRadius: '12px', display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{ width: '40px', height: '40px', borderRadius: '10px', background: 'rgba(56, 189, 248, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#38bdf8' }}><Shield size={18} /></div>
                    <div><div style={{ fontSize: '1.3rem', fontWeight: '700', color: '#fff' }}>{invV2Summary?.productionResources || 0}</div><div style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.5)' }}>Producción</div></div>
                  </div>
                  <div className="glass" style={{ padding: '14px 18px', borderRadius: '12px', display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{ width: '40px', height: '40px', borderRadius: '10px', background: 'rgba(217, 70, 239, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#d946ef' }}><Users size={18} /></div>
                    <div><div style={{ fontSize: '1.3rem', fontWeight: '700', color: '#fff' }}>{invV2Summary?.resourcesWithoutOwnerCandidate || 0}</div><div style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.5)' }}>Sin Custodio</div></div>
                  </div>
                </div>

                {/* Tag Compliance Matrix + Distributions */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                  {/* Tag Compliance Matrix */}
                  <div className="dashboard-card glass">
                    <div className="card-header" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '12px', marginBottom: '14px' }}>
                      <span className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><Tag size={18} /> Matriz de Tags Obligatorias</span>
                    </div>
                    {invV2TagCompliance?.matrix?.map((item) => (
                      <div key={item.tag} style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '8px 0', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                        <span style={{ width: '100px', fontSize: '0.85rem', color: '#fff', fontWeight: '600' }}>{item.tag}</span>
                        <div style={{ flex: 1, background: 'rgba(255,255,255,0.06)', borderRadius: '6px', height: '24px', overflow: 'hidden', position: 'relative' }}>
                          <div style={{ width: `${item.compliancePercentage}%`, height: '100%', background: item.compliancePercentage >= 80 ? 'linear-gradient(90deg, #22c55e, #10b981)' : item.compliancePercentage >= 50 ? 'linear-gradient(90deg, #f59e0b, #eab308)' : 'linear-gradient(90deg, #ef4444, #f43f5e)', borderRadius: '6px', transition: 'width 0.5s ease' }} />
                          <span style={{ position: 'absolute', right: '8px', top: '50%', transform: 'translateY(-50%)', fontSize: '0.7rem', color: '#fff', fontWeight: '700' }}>{item.compliancePercentage}%</span>
                        </div>
                        <span style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.4)', width: '80px', textAlign: 'right' }}>{item.present}/{item.present + item.missing}</span>
                      </div>
                    ))}
                    {invV2TagCompliance && (
                      <div style={{ marginTop: '12px', padding: '10px', background: 'rgba(99, 102, 241, 0.08)', borderRadius: '8px', textAlign: 'center' }}>
                        <span style={{ fontSize: '0.8rem', color: 'rgba(255,255,255,0.6)' }}>Cumplimiento Global: </span>
                        <span style={{ fontSize: '1.1rem', fontWeight: '700', color: invV2TagCompliance.overallCompliancePercentage >= 80 ? '#22c55e' : '#f59e0b' }}>{invV2TagCompliance.overallCompliancePercentage}%</span>
                      </div>
                    )}
                  </div>

                  {/* Distributions */}
                  <div className="dashboard-card glass">
                    <div className="card-header" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '12px', marginBottom: '14px' }}>
                      <span className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><Layers size={18} /> Distribución por Tipo</span>
                    </div>
                    {invV2Summary?.byResourceType?.slice(0, 8).map((item) => (
                      <div key={item.key} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '5px 0' }}>
                        <span style={{ flex: 1, fontSize: '0.8rem', color: 'rgba(255,255,255,0.7)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.key}</span>
                        <div style={{ width: '120px', background: 'rgba(255,255,255,0.06)', borderRadius: '4px', height: '16px', overflow: 'hidden' }}>
                          <div style={{ width: `${item.percentage}%`, height: '100%', background: 'linear-gradient(90deg, var(--primary), #818cf8)', borderRadius: '4px' }} />
                        </div>
                        <span style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.5)', width: '55px', textAlign: 'right' }}>{item.count}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Environment + Region Distributions */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '16px' }}>
                  <div className="dashboard-card glass">
                    <div className="card-header" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '10px', marginBottom: '12px' }}>
                      <span className="card-title" style={{ fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '6px' }}><Tag size={16} /> Por Ambiente</span>
                    </div>
                    {invV2Summary?.byEnvironment?.slice(0, 6).map((item) => (
                      <div key={item.key} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: '0.82rem' }}>
                        <span style={{ color: 'rgba(255,255,255,0.7)' }}>{item.key}</span>
                        <span style={{ color: '#fff', fontWeight: '600' }}>{item.count} <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: '0.7rem' }}>({item.percentage}%)</span></span>
                      </div>
                    ))}
                  </div>
                  <div className="dashboard-card glass">
                    <div className="card-header" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '10px', marginBottom: '12px' }}>
                      <span className="card-title" style={{ fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '6px' }}><MapPin size={16} /> Por Región</span>
                    </div>
                    {invV2Summary?.byRegion?.slice(0, 6).map((item) => (
                      <div key={item.key} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: '0.82rem' }}>
                        <span style={{ color: 'rgba(255,255,255,0.7)' }}>{item.key}</span>
                        <span style={{ color: '#fff', fontWeight: '600' }}>{item.count}</span>
                      </div>
                    ))}
                  </div>
                  <div className="dashboard-card glass">
                    <div className="card-header" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '10px', marginBottom: '12px' }}>
                      <span className="card-title" style={{ fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '6px' }}><Globe size={16} /> Por Suscripción</span>
                    </div>
                    {invV2Summary?.bySubscription?.slice(0, 6).map((item) => (
                      <div key={item.key} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: '0.82rem' }}>
                        <span style={{ color: 'rgba(255,255,255,0.7)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '200px' }}>{item.key}</span>
                        <span style={{ color: '#fff', fontWeight: '600' }}>{item.count}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <TrendPanel history={history} loading={historyLoading} />

                {/* Actions Bar */}
                <div className="dashboard-card glass" style={{ padding: '14px 18px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    {invV2LastUpdated && <span style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.4)' }}>Última actualización: {new Date(invV2LastUpdated).toLocaleString('es-CO')}</span>}
                  </div>
                  <div style={{ display: 'flex', gap: '10px' }}>
                    <button className="btn btn-secondary" onClick={handleExportCSV} style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 14px' }}>
                      <Download size={14} /> Exportar CSV (Legacy)
                    </button>
                    <button className="btn btn-primary" onClick={handleInvV2ExportCSV} style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 14px' }}>
                      <Download size={14} /> Exportar Inventario Gobernanza
                    </button>
                    <button className="btn btn-secondary" onClick={() => { fetchInvV2Summary(); fetchInvV2TagCompliance(); fetchInvV2Resources(); }} style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 14px' }}>
                      <RefreshCw size={14} /> Refrescar
                    </button>
                  </div>
                </div>

                {/* El chat vive ahora en la consola lateral, accesible desde
                    cualquier pestaña, en vez de repetirse dentro de cada una. */}
                <div>
                  <div className="dashboard-card glass">
                    <div className="card-header" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '10px', marginBottom: '12px' }}>
                      <span className="card-title" style={{ fontSize: '0.9rem' }}>📊 Snapshots & Reportes Excel</span>
                    </div>
                    <div style={{ display: 'flex', gap: '10px', marginBottom: '10px' }}>
                      <a href={`${API_URL}/api/inventory/download/Azure_IaC_Inventario.xlsx`} target="_blank" rel="noopener noreferrer" className="btn btn-primary" style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 14px', textDecoration: 'none', fontSize: '0.82rem' }}>
                        <Download size={14} /> Descargar Master Excel
                      </a>
                    </div>
                    {snapshots.length > 0 && (
                      <div style={{ maxHeight: '200px', overflowY: 'auto' }}>
                        {snapshots.map((s: any, i: number) => (
                          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid rgba(255,255,255,0.04)', fontSize: '0.8rem' }}>
                            <span style={{ color: 'rgba(255,255,255,0.6)' }}>{s.filename}</span>
                            <a href={`${API_URL}/api/inventory/download/${s.filename}`} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--primary)', fontSize: '0.75rem' }}>Descargar</a>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                <div className="section-head">
                  <span className="section-title">Explorador del inventario</span>
                  <span className="section-desc">Todos los recursos de las suscripciones seleccionadas, con su cumplimiento de tags y su clasificación de gobernanza. La búsqueda y los filtros se resuelven en Azure, no en el navegador.</span>
                </div>
                {/* Filters Bar */}
                <div className="dashboard-card glass" style={{ padding: '14px 18px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                    <div style={{ position: 'relative', flex: '1 1 250px' }}>
                      <Search size={14} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'rgba(255,255,255,0.3)' }} />
                      <input
                        type="text"
                        placeholder="Buscar por nombre, tipo, resource group, ID..."
                        value={invV2Search}
                        onChange={(e) => { setInvV2Search(e.target.value); setInvV2Page(1); }}
                        style={{ width: '100%', padding: '8px 10px 8px 32px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', color: '#fff', fontSize: '0.82rem', outline: 'none' }}
                      />
                    </div>
                    <select value={invV2EnvFilter} onChange={(e) => { setInvV2EnvFilter(e.target.value); setInvV2Page(1); }} style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', color: '#fff', fontSize: '0.82rem' }}>
                      <option value="">Todos los Ambientes</option>
                      {invV2Summary?.byEnvironment?.map(e => <option key={e.key} value={e.key}>{e.key} ({e.count})</option>)}
                    </select>
                    <select value={invV2LocationFilter} onChange={(e) => { setInvV2LocationFilter(e.target.value); setInvV2Page(1); }} style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', color: '#fff', fontSize: '0.82rem' }}>
                      <option value="">Todas las Regiones</option>
                      {invV2Summary?.byRegion?.map(r => <option key={r.key} value={r.key}>{r.key} ({r.count})</option>)}
                    </select>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem', color: 'rgba(255,255,255,0.6)', cursor: 'pointer' }}>
                      <input type="checkbox" checked={invV2OnlyNonCompliant} onChange={(e) => { setInvV2OnlyNonCompliant(e.target.checked); setInvV2Page(1); }} style={{ accentColor: 'var(--primary)' }} />
                      Solo no conformes
                    </label>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem', color: 'rgba(255,255,255,0.6)', cursor: 'pointer' }}>
                      <input type="checkbox" checked={invV2OnlyShadowIt} onChange={(e) => { setInvV2OnlyShadowIt(e.target.checked); setInvV2Page(1); }} style={{ accentColor: '#a855f7' }} />
                      Solo Shadow IT
                    </label>
                    {(invV2Search || invV2EnvFilter || invV2LocationFilter || invV2OnlyNonCompliant || invV2OnlyShadowIt) && (
                      <button onClick={() => { setInvV2Search(''); setInvV2EnvFilter(''); setInvV2LocationFilter(''); setInvV2TypeFilter(''); setInvV2OnlyNonCompliant(false); setInvV2OnlyShadowIt(false); setInvV2Page(1); }} style={{ background: 'rgba(244, 63, 94, 0.15)', border: '1px solid rgba(244, 63, 94, 0.3)', borderRadius: '8px', padding: '8px 12px', color: '#f43f5e', fontSize: '0.8rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <X size={14} /> Limpiar filtros
                      </button>
                    )}
                  </div>
                </div>

                {/* Resource Table */}
                <div className="dashboard-card glass" style={{ padding: '0', overflow: 'hidden' }}>
                  <div style={{ padding: '14px 18px', borderBottom: '1px solid rgba(255,255,255,0.08)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: '700', fontSize: '0.95rem', color: '#fff' }}>Explorador de Recursos ({invV2Total.toLocaleString()} recursos)</span>
                    {invV2Loading && <RefreshCw size={16} className="spinning" style={{ color: 'var(--primary)' }} />}
                  </div>
                  <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                      <thead>
                        <tr style={{ background: 'rgba(255,255,255,0.03)' }}>
                          <th style={{ padding: '10px 14px', textAlign: 'left', color: 'rgba(255,255,255,0.5)', fontWeight: '600', whiteSpace: 'nowrap' }}>Nombre</th>
                          <th style={{ padding: '10px 14px', textAlign: 'left', color: 'rgba(255,255,255,0.5)', fontWeight: '600', whiteSpace: 'nowrap' }}>Tipo</th>
                          <th style={{ padding: '10px 14px', textAlign: 'left', color: 'rgba(255,255,255,0.5)', fontWeight: '600', whiteSpace: 'nowrap' }}>Resource Group</th>
                          <th style={{ padding: '10px 14px', textAlign: 'left', color: 'rgba(255,255,255,0.5)', fontWeight: '600', whiteSpace: 'nowrap' }}>Suscripción</th>
                          <th style={{ padding: '10px 14px', textAlign: 'left', color: 'rgba(255,255,255,0.5)', fontWeight: '600', whiteSpace: 'nowrap' }}>Región</th>
                          <th style={{ padding: '10px 14px', textAlign: 'left', color: 'rgba(255,255,255,0.5)', fontWeight: '600', whiteSpace: 'nowrap' }}>Environment</th>
                          <th style={{ padding: '10px 14px', textAlign: 'center', color: 'rgba(255,255,255,0.5)', fontWeight: '600', whiteSpace: 'nowrap' }}>Tags %</th>
                          <th style={{ padding: '10px 14px', textAlign: 'center', color: 'rgba(255,255,255,0.5)', fontWeight: '600', whiteSpace: 'nowrap' }}>Shadow IT</th>
                          <th style={{ padding: '10px 14px', textAlign: 'center', color: 'rgba(255,255,255,0.5)', fontWeight: '600', whiteSpace: 'nowrap' }}>Acciones</th>
                        </tr>
                      </thead>
                      <tbody>
                        {invV2Resources.map((r, idx) => (
                          <tr key={r.id || idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', transition: 'background 0.15s' }} onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.03)')} onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}>
                            <td style={{ padding: '10px 14px', color: '#fff', fontWeight: '500', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</td>
                            <td style={{ padding: '10px 14px', color: 'rgba(255,255,255,0.6)' }}>{r.typeDisplayName || r.type?.split('/').pop()}</td>
                            <td style={{ padding: '10px 14px', color: 'rgba(255,255,255,0.6)', maxWidth: '160px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.resourceGroup}</td>
                            <td style={{ padding: '10px 14px', color: 'rgba(255,255,255,0.5)', maxWidth: '160px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.subscriptionName}</td>
                            <td style={{ padding: '10px 14px', color: 'rgba(255,255,255,0.5)' }}>{r.location}</td>
                            <td style={{ padding: '10px 14px' }}>
                              <span style={{ padding: '3px 8px', borderRadius: '6px', fontSize: '0.72rem', fontWeight: '600', background: r.environment ? (r.governance?.isProduction ? 'rgba(239, 68, 68, 0.15)' : 'rgba(16, 185, 129, 0.15)') : 'rgba(255,255,255,0.06)', color: r.environment ? (r.governance?.isProduction ? '#ef4444' : '#10b981') : 'rgba(255,255,255,0.3)' }}>{r.environment || 'N/A'}</span>
                            </td>
                            <td style={{ padding: '10px 14px', textAlign: 'center' }}>
                              <span style={{ padding: '3px 8px', borderRadius: '6px', fontSize: '0.72rem', fontWeight: '700', background: r.mandatoryTags.isCompliant ? 'rgba(16, 185, 129, 0.15)' : r.mandatoryTags.compliancePercentage >= 50 ? 'rgba(245, 158, 11, 0.15)' : 'rgba(239, 68, 68, 0.15)', color: r.mandatoryTags.isCompliant ? '#10b981' : r.mandatoryTags.compliancePercentage >= 50 ? '#f59e0b' : '#ef4444' }}>{r.mandatoryTags.compliancePercentage}%</span>
                            </td>
                            <td style={{ padding: '10px 14px', textAlign: 'center' }}>
                              {r.governance.isShadowItCandidate ? (
                                <span title={r.governance.shadowItReason || ''} style={{ padding: '3px 8px', borderRadius: '6px', fontSize: '0.72rem', fontWeight: '600', background: 'rgba(168, 85, 247, 0.15)', color: '#a855f7', cursor: 'help' }}>⚠ Candidato</span>
                              ) : (
                                <span style={{ color: 'rgba(255,255,255,0.2)', fontSize: '0.72rem' }}>—</span>
                              )}
                            </td>
                            <td style={{ padding: '10px 14px', textAlign: 'center' }}>
                              <div style={{ display: 'flex', gap: '4px', justifyContent: 'center' }}>
                                <button onClick={() => { setInvV2SelectedResource(r); setInvV2DetailOpen(true); }} title="Ver detalle" style={{ background: 'rgba(99, 102, 241, 0.15)', border: 'none', borderRadius: '6px', padding: '5px 7px', cursor: 'pointer', color: 'var(--primary)' }}><Eye size={14} /></button>
                                <button onClick={() => copyToClipboard(r.id, 'Resource ID')} title="Copiar ID" style={{ background: 'rgba(255,255,255,0.06)', border: 'none', borderRadius: '6px', padding: '5px 7px', cursor: 'pointer', color: 'rgba(255,255,255,0.5)' }}><Clipboard size={14} /></button>
                              </div>
                            </td>
                          </tr>
                        ))}
                        {invV2Resources.length === 0 && !invV2Loading && (
                          <tr><td colSpan={9} style={{ padding: '20px 12px', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>No se encontraron recursos con los filtros actuales</td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                  {/* Pagination */}
                  <div style={{ padding: '12px 18px', borderTop: '1px solid rgba(255,255,255,0.08)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.8rem', color: 'rgba(255,255,255,0.4)' }}>Mostrando {Math.min((invV2Page - 1) * invV2PageSize + 1, invV2Total)} a {Math.min(invV2Page * invV2PageSize, invV2Total)} de {invV2Total.toLocaleString()} recursos</span>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                      <button disabled={invV2Page <= 1} onClick={() => setInvV2Page(p => Math.max(1, p - 1))} className="btn btn-secondary" style={{ padding: '6px 12px', fontSize: '0.8rem', opacity: invV2Page <= 1 ? 0.4 : 1 }}>Anterior</button>
                      <span style={{ fontSize: '0.8rem', color: 'rgba(255,255,255,0.5)' }}>Página {invV2Page} de {Math.max(1, Math.ceil(invV2Total / invV2PageSize))}</span>
                      <button disabled={invV2Page >= Math.ceil(invV2Total / invV2PageSize)} onClick={() => setInvV2Page(p => p + 1)} className="btn btn-secondary" style={{ padding: '6px 12px', fontSize: '0.8rem', opacity: invV2Page >= Math.ceil(invV2Total / invV2PageSize) ? 0.4 : 1 }}>Siguiente</button>
                    </div>
                  </div>
                </div>

                {/* Resource Detail Drawer/Modal */}
                {invV2DetailOpen && invV2SelectedResource && (
                  <div style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: '520px', background: 'rgba(15, 15, 25, 0.98)', backdropFilter: 'blur(20px)', borderLeft: '1px solid rgba(255,255,255,0.1)', zIndex: 1000, display: 'flex', flexDirection: 'column', overflow: 'hidden', animation: 'slideInRight 0.3s ease' }}>
                    <div style={{ padding: '18px 20px', borderBottom: '1px solid rgba(255,255,255,0.08)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <h3 style={{ margin: 0, fontSize: '1rem', color: '#fff' }}>Detalle del Recurso</h3>
                      <button onClick={() => setInvV2DetailOpen(false)} style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.5)', cursor: 'pointer' }}><X size={20} /></button>
                    </div>
                    <div style={{ flex: 1, overflowY: 'auto', padding: '18px 20px' }}>
                      <div style={{ marginBottom: '16px' }}>
                        <div style={{ fontSize: '1.15rem', fontWeight: '700', color: '#fff', marginBottom: '4px' }}>{invV2SelectedResource.name}</div>
                        <div style={{ fontSize: '0.8rem', color: 'rgba(255,255,255,0.4)' }}>{invV2SelectedResource.type}</div>
                      </div>
                      {/* Resource ID */}
                      <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '8px', padding: '10px 12px', marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <code style={{ flex: 1, fontSize: '0.7rem', color: 'rgba(255,255,255,0.5)', wordBreak: 'break-all' }}>{invV2SelectedResource.id}</code>
                        <button onClick={() => copyToClipboard(invV2SelectedResource.id, 'Resource ID')} style={{ background: 'rgba(99,102,241,0.15)', border: 'none', borderRadius: '6px', padding: '5px 8px', cursor: 'pointer', color: 'var(--primary)', flexShrink: 0 }}><Copy size={12} /></button>
                      </div>
                      {/* Info Grid */}
                      {[{l: 'Suscripción', v: invV2SelectedResource.subscriptionName}, {l: 'Resource Group', v: invV2SelectedResource.resourceGroup}, {l: 'Región', v: invV2SelectedResource.location}, {l: 'Environment', v: invV2SelectedResource.environment || 'N/A'}, {l: 'Customer', v: invV2SelectedResource.customer || 'N/A'}, {l: 'Product', v: invV2SelectedResource.product || 'N/A'}, {l: 'Suite', v: invV2SelectedResource.suite || 'N/A'}, {l: 'Platform', v: invV2SelectedResource.platform || 'N/A'}, {l: 'Tenant', v: invV2SelectedResource.tenant || 'N/A'}, {l: 'SKU', v: invV2SelectedResource.skuName || 'N/A'}, {l: 'Estado', v: invV2SelectedResource.provisioningState || 'N/A'}, {l: 'Custodio', v: invV2SelectedResource.governance.ownerCandidate || 'Sin asignar'}].map(({l, v}) => (
                        <div key={l} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid rgba(255,255,255,0.04)', fontSize: '0.82rem' }}>
                          <span style={{ color: 'rgba(255,255,255,0.4)' }}>{l}</span>
                          <span style={{ color: '#fff', fontWeight: '500', maxWidth: '250px', textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis' }}>{v}</span>
                        </div>
                      ))}
                      {/* Compliance */}
                      <div style={{ marginTop: '16px', padding: '12px', background: 'rgba(255,255,255,0.04)', borderRadius: '10px' }}>
                        <div style={{ fontWeight: '700', fontSize: '0.85rem', color: '#fff', marginBottom: '8px' }}>Cumplimiento de Tags Obligatorias</div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                          <div style={{ flex: 1, background: 'rgba(255,255,255,0.06)', borderRadius: '6px', height: '20px', overflow: 'hidden' }}>
                            <div style={{ width: `${invV2SelectedResource.mandatoryTags.compliancePercentage}%`, height: '100%', background: invV2SelectedResource.mandatoryTags.isCompliant ? 'linear-gradient(90deg, #22c55e, #10b981)' : 'linear-gradient(90deg, #f59e0b, #eab308)', borderRadius: '6px' }} />
                          </div>
                          <span style={{ fontWeight: '700', color: invV2SelectedResource.mandatoryTags.isCompliant ? '#22c55e' : '#f59e0b', fontSize: '0.9rem' }}>{invV2SelectedResource.mandatoryTags.present}/{invV2SelectedResource.mandatoryTags.totalRequired}</span>
                        </div>
                        {invV2SelectedResource.mandatoryTags.missing.length > 0 && (
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                            {invV2SelectedResource.mandatoryTags.missing.map(t => (
                              <span key={t} style={{ padding: '2px 8px', borderRadius: '4px', fontSize: '0.7rem', background: 'rgba(239,68,68,0.15)', color: '#ef4444' }}>❌ {t}</span>
                            ))}
                          </div>
                        )}
                      </div>
                      {/* Shadow IT */}
                      {invV2SelectedResource.governance.isShadowItCandidate && (
                        <div style={{ marginTop: '12px', padding: '12px', background: 'rgba(168,85,247,0.08)', border: '1px solid rgba(168,85,247,0.2)', borderRadius: '10px' }}>
                          <div style={{ fontWeight: '700', fontSize: '0.85rem', color: '#a855f7', marginBottom: '4px' }}>⚠ Candidato Shadow IT</div>
                          <div style={{ fontSize: '0.8rem', color: 'rgba(255,255,255,0.6)' }}>{invV2SelectedResource.governance.shadowItReason}</div>
                        </div>
                      )}
                      {/* All Tags */}
                      <div style={{ marginTop: '16px' }}>
                        <div style={{ fontWeight: '700', fontSize: '0.85rem', color: '#fff', marginBottom: '8px' }}>Todas las Tags ({Object.keys(invV2SelectedResource.tags).length})</div>
                        {Object.entries(invV2SelectedResource.tags).length > 0 ? Object.entries(invV2SelectedResource.tags).map(([k, v]) => (
                          <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid rgba(255,255,255,0.03)', fontSize: '0.78rem' }}>
                            <span style={{ color: 'rgba(255,255,255,0.4)', fontFamily: 'monospace' }}>{k}</span>
                            <span style={{ color: '#fff', maxWidth: '250px', textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis' }}>{v}</span>
                          </div>
                        )) : <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: '0.8rem' }}>Sin tags asignadas</div>}
                      </div>
                      {/* Data Completeness */}
                      <div style={{ marginTop: '16px', padding: '12px', background: 'rgba(255,255,255,0.04)', borderRadius: '10px' }}>
                        <div style={{ fontWeight: '700', fontSize: '0.85rem', color: '#fff', marginBottom: '6px' }}>Completitud de Datos</div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <div style={{ flex: 1, background: 'rgba(255,255,255,0.06)', borderRadius: '6px', height: '16px', overflow: 'hidden' }}>
                            <div style={{ width: `${invV2SelectedResource.governance.dataCompletenessScore}%`, height: '100%', background: 'linear-gradient(90deg, var(--primary), #818cf8)', borderRadius: '6px' }} />
                          </div>
                          <span style={{ fontSize: '0.85rem', fontWeight: '700', color: 'var(--primary)' }}>{invV2SelectedResource.governance.dataCompletenessScore}%</span>
                        </div>
                      </div>
                    </div>
                    {/* Drawer Footer */}
                    <div style={{ padding: '14px 20px', borderTop: '1px solid rgba(255,255,255,0.08)', display: 'flex', gap: '8px' }}>
                      <button onClick={() => copyToClipboard(invV2SelectedResource.id, 'Resource ID')} className="btn btn-secondary" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', padding: '8px' }}><Copy size={14} /> Copiar ID</button>
                      <button onClick={() => copyToClipboard(invV2SelectedResource.name, 'Nombre')} className="btn btn-secondary" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', padding: '8px' }}><Clipboard size={14} /> Copiar Nombre</button>
                      <button onClick={() => { askAgent('inventory', `Dame información detallada sobre el recurso ${invV2SelectedResource.name} en el resource group ${invV2SelectedResource.resourceGroup}`); setInvV2DetailOpen(false); }} className="btn btn-primary" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', padding: '8px' }}><Send size={14} /> Preguntar IA</button>
                    </div>
                  </div>
                )}
                {/* Drawer backdrop */}
                {invV2DetailOpen && <div onClick={() => setInvV2DetailOpen(false)} style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', zIndex: 999 }} />}

                <div className="section-head">
                  <span className="section-title">Reportes y automatización</span>
                  <span className="section-desc">Envío programado del resumen de gobernanza al canal de Teams y descarga del inventario maestro.</span>
                </div>
                {/* Microsoft Teams Integration - Preserved */}
                <div className="dashboard-card glass">
                  <div className="card-header" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '12px', marginBottom: '16px' }}>
                    <span className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>🔔 Integración Microsoft Teams</span>
                  </div>
                  <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
                    <div style={{ flex: 1 }}>
                      <label style={{ fontSize: '0.8rem', color: 'rgba(255,255,255,0.5)', display: 'block', marginBottom: '4px' }}>Webhook URL</label>
                      <input type="text" placeholder="https://...webhook.office.com/..." value={teamsWebhookUrl} onChange={(e) => { setTeamsWebhookUrl(e.target.value); localStorage.setItem('teamsWebhookUrl', e.target.value); }} style={{ width: '100%', padding: '10px 14px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', color: '#fff', fontSize: '0.85rem' }} />
                    </div>
                    <select value={teamsAlertType} onChange={(e) => setTeamsAlertType(e.target.value as any)} style={{ padding: '10px 14px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', color: '#fff', fontSize: '0.85rem' }}>
                      <option value="all">Todos</option>
                      <option value="finops">FinOps</option>
                      <option value="secops">SecOps</option>
                    </select>
                    <button className="btn btn-primary" disabled={isSendingWebhook || !teamsWebhookUrl} onClick={async () => { setIsSendingWebhook(true); setWebhookStatus(null); try { const r = await apiFetch(`${API_URL}/api/integration/test-webhook`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ webhook_url: teamsWebhookUrl, alert_type: teamsAlertType }) }); const d = await r.json(); setWebhookStatus({ success: r.ok, message: d.message || d.detail || 'OK' }); } catch { setWebhookStatus({ success: false, message: 'Error de red' }); } setIsSendingWebhook(false); }} style={{ padding: '10px 18px', whiteSpace: 'nowrap' }}>
                      {isSendingWebhook ? 'Enviando...' : 'Enviar Alerta'}
                    </button>
                  </div>
                  {webhookStatus && <div style={{ marginTop: '8px', padding: '8px 12px', borderRadius: '6px', fontSize: '0.8rem', background: webhookStatus.success ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)', color: webhookStatus.success ? '#10b981' : '#ef4444' }}>{webhookStatus.message}</div>}
                </div>

            </div>
            </SectionBoundary>
          )}

          {/* Active View: FinOps - FULL SCOPE */}
          {activeTab === 'finops' && (
            <SectionBoundary name="FinOps">
            <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

                {/* KPI Header */}
                <div className="dashboard-card glass">
                  <div className="card-header" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '14px', marginBottom: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span className="card-title" style={{ fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <span style={{ fontSize: '1.5rem' }}>💰</span> Reporte y Ciclo de Vida de Ahorro Financiero (FinOps)
                    </span>
                    <div style={{ display: 'flex', gap: '12px' }}>
                      <span className="badge badge-warning" style={{ padding: '6px 14px', fontSize: '0.85rem' }}>
                        Potencial: ${finopsReport?.savings_lifecycle?.potential_savings_usd || '0.00'} USD/mes
                      </span>
                      <span className="badge badge-info" style={{ padding: '6px 14px', fontSize: '0.85rem', backgroundColor: 'rgba(59, 130, 246, 0.15)', color: '#60a5fa', borderColor: 'rgba(59, 130, 246, 0.3)' }}>
                        Aprobado: ${finopsReport?.savings_lifecycle?.approved_savings_usd || '0.00'} USD/mes
                      </span>
                      <span className="badge badge-success" style={{ padding: '6px 14px', fontSize: '0.85rem' }}>
                        Realizado: ${finopsReport?.savings_lifecycle?.realized_savings_usd || '0.00'} USD/mes
                      </span>
                    </div>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '12px' }}>
                    {[
                      { label: 'Discos Huérfanos', val: finopsReport?.unattached_disks?.length || 0, icon: '💾', color: 'var(--danger)' },
                      { label: 'IPs Sin Asociar', val: finopsReport?.unassociated_ips?.length || 0, icon: '🌐', color: 'var(--warning)' },
                      { label: 'NICs Inactivas', val: finopsReport?.orphaned_nics?.length || 0, icon: '🔌', color: 'var(--warning)' },
                      { label: 'App Plans Vacíos', val: finopsReport?.empty_app_plans?.length || 0, icon: '📦', color: 'var(--accent)' },
                      { label: 'Snapshots Olvidados', val: finopsReport?.old_snapshots?.length || 0, icon: '📸', color: 'var(--text-secondary)' },
                    ].map(({ label, val, icon, color }) => (
                      <div key={label} className="stat-card" style={{ background: 'rgba(255,255,255,0.025)', padding: '14px', textAlign: 'center', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.06)' }}>
                        <div style={{ fontSize: '1.6rem', marginBottom: '4px' }}>{icon}</div>
                        <div className="stat-value" style={{ color: val > 0 ? color : 'var(--success)', fontSize: '1.6rem' }}>{val}</div>
                        <div className="stat-label" style={{ fontSize: '0.7rem', marginTop: '2px' }}>{label}</div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="section-head">
                  <span className="section-title">Desperdicio identificado</span>
                  <span className="section-desc">Recursos que se pueden apagar o borrar sin afectar a nada en marcha. El costo sale de la factura donde hay cobertura y del catálogo de precios donde no, y cada cifra dice cuál es.</span>
                </div>
                {/* Grid Row: Savings Breakdown & Chatbot */}
                <div className="dashboard-sections" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '14px' }}>
                  {/* Left Card: Desglose de Ahorro por Ciclo de Vida */}
                  <div className="dashboard-card glass" style={{ maxHeight: '420px', overflowY: 'auto' }}>
                    <div className="card-header" style={{ position: 'sticky', top: 0, background: '#121826', zIndex: 10 }}><span className="card-title">📊 Ciclo de Vida de Ahorro FinOps (USD)</span><span className="badge badge-success">Métricas Reales</span></div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginTop: '16px', padding: '0 10px 10px 10px' }}>
                      {[
                        { label: 'Ahorro Potencial (Identificado)', val: finopsReport?.savings_lifecycle?.potential_savings_usd || 0, color: 'var(--warning)', desc: 'Optimización detectada en Azure pendiente de aprobación o remediación.' },
                        { label: 'Ahorro Aprobado (Owner Aceptado)', val: finopsReport?.savings_lifecycle?.approved_savings_usd || 0, color: '#60a5fa', desc: 'Recomendaciones aprobadas listas para ser remediadas por el equipo.' },
                        { label: 'Ahorro Realizado (Factura Reducida)', val: finopsReport?.savings_lifecycle?.realized_savings_usd || 0, color: 'var(--success)', desc: 'Costo que efectivamente bajó al aplicar y cerrar los hallazgos.' },
                      ].map(({ label, val, color, desc }) => {
                        const maxVal = Math.max(1, finopsReport?.savings_lifecycle?.potential_savings_usd || 0);
                        const pct = (val / maxVal * 100).toFixed(0);
                        return (
                          <div key={label} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                              <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#fff' }}>{label}</span>
                              <span style={{ color: color, fontWeight: 700, fontSize: '0.9rem' }}>${Number(val ?? 0).toFixed(2)} USD</span>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                              <div style={{ flex: 1, height: '8px', borderRadius: '4px', backgroundColor: 'rgba(255,255,255,0.07)', overflow: 'hidden' }}>
                                <div style={{ width: `${pct}%`, height: '100%', backgroundColor: color, borderRadius: '4px' }} />
                              </div>
                              <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>{pct}%</span>
                            </div>
                            <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>{desc}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                </div>

                {/* Discos Huérfanos */}
                <div className="dashboard-card glass">
                  <div className="card-header"><span className="card-title">💾 Discos sin Máquina Virtual (Unattached Managed Disks)</span><span className="badge badge-danger">Costo Activo Sin Uso</span></div>
                  <div className="custom-table-container">
                    <table className="custom-table">
                      <thead><tr><th>Nombre</th><th>Resource Group</th><th>SKU</th><th>Tamaño</th><th>Región</th><th>Acción</th></tr></thead>
                      <tbody>
                        {(finopsReport?.unattached_disks || []).length > 0 ? (finopsReport!.unattached_disks.map((d, i) => (
                          <tr key={i}>
                            <td style={{ fontWeight: 600 }}>{d.name}</td><td>{d.resourceGroup}</td>
                            <td><span className="badge badge-info">{d.sku || 'Standard_LRS'}</span></td>
                            <td>{d.sizeGB || '?'} GB</td><td><code>{d.location}</code></td>
                            <td><button className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '0.72rem' }} onClick={() => askAgent('finops', `Analiza el disco huérfano ${d.name} en ${d.resourceGroup}. ¿Es seguro eliminarlo? ¿Qué impacto financiero tiene?`)}>Analizar →</button></td>
                          </tr>
                        ))) : <tr><td colSpan={6} style={{ textAlign: 'center', padding: '16px', color: 'var(--success)' }}>✅ No hay discos huérfanos</td></tr>}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* IPs Públicas sin Uso */}
                <div className="dashboard-card glass">
                  <div className="card-header"><span className="card-title">🌐 IPs Públicas Reservadas sin Asociar</span><span className="badge badge-warning">$3.60 USD/mes c/u</span></div>
                  <div className="custom-table-container">
                    <table className="custom-table">
                      <thead><tr><th>Nombre</th><th>Resource Group</th><th>Dirección IP</th><th>SKU</th><th>Región</th><th>Acción</th></tr></thead>
                      <tbody>
                        {(finopsReport?.unassociated_ips || []).length > 0 ? (finopsReport!.unassociated_ips.map((ip, i) => (
                          <tr key={i}>
                            <td style={{ fontWeight: 600 }}>{ip.name}</td><td>{ip.resourceGroup}</td>
                            <td><code>{ip.ipAddress || '—'}</code></td>
                            <td><span className="badge badge-info">{ip.sku || 'Standard'}</span></td>
                            <td><code>{ip.location}</code></td>
                            <td><button className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '0.72rem' }} onClick={() => askAgent('finops', `¿Es seguro eliminar la IP pública ${ip.name}? ¿Qué recurso la tenía asociada antes?`)}>Analizar →</button></td>
                          </tr>
                        ))) : <tr><td colSpan={6} style={{ textAlign: 'center', padding: '16px', color: 'var(--success)' }}>✅ No hay IPs públicas libres</td></tr>}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* NICs Huérfanas + App Plans Vacíos (2 columnas) */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '14px' }}>
                  <div className="dashboard-card glass">
                    <div className="card-header"><span className="card-title">🔌 Interfaces de Red Huérfanas (NICs)</span><span className="badge badge-warning">Residuos de VMs</span></div>
                    <div className="custom-table-container">
                      <table className="custom-table">
                        <thead><tr><th>Nombre</th><th>Resource Group</th><th>Región</th><th>Acción</th></tr></thead>
                        <tbody>
                          {(finopsReport?.orphaned_nics || []).length > 0 ? (finopsReport!.orphaned_nics.map((n, i) => (
                            <tr key={i}><td style={{ fontWeight: 600 }}>{n.name}</td><td>{n.resourceGroup}</td><td><code>{n.location}</code></td>
                              <td><button className="btn btn-secondary" style={{ padding: '3px 6px', fontSize: '0.72rem' }} onClick={() => askAgent('finops', `Analiza la NIC huérfana ${n.name}`)}>Ver</button></td></tr>
                          ))) : <tr><td colSpan={4} style={{ textAlign: 'center', padding: '14px', color: 'var(--success)' }}>✅ Sin NICs huérfanas</td></tr>}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  <div className="dashboard-card glass">
                    <div className="card-header"><span className="card-title">📦 App Service Plans sin Aplicaciones</span><span className="badge badge-danger">Costo Fijo Sin ROI</span></div>
                    <div className="custom-table-container">
                      <table className="custom-table">
                        <thead><tr><th>Nombre</th><th>Resource Group</th><th>SKU</th><th>Apps</th><th>Acción</th></tr></thead>
                        <tbody>
                          {(finopsReport?.empty_app_plans || []).length > 0 ? (finopsReport!.empty_app_plans.map((p, i) => (
                            <tr key={i}><td style={{ fontWeight: 600 }}>{p.name}</td><td>{p.resourceGroup}</td>
                              <td><span className="badge badge-warning">{p.sku || '?'}</span></td>
                              <td style={{ color: 'var(--danger)', fontWeight: 700 }}>{p.numberOfSites ?? 0}</td>
                              <td><button className="btn btn-secondary" style={{ padding: '3px 6px', fontSize: '0.72rem' }} onClick={() => askAgent('finops', `El App Service Plan ${p.name} no tiene apps. ¿Es seguro eliminarlo y cuánto nos ahorramos?`)}>Ver</button></td></tr>
                          ))) : <tr><td colSpan={5} style={{ textAlign: 'center', padding: '14px', color: 'var(--success)' }}>✅ Sin App Plans vacíos</td></tr>}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>

                {/* Snapshots Olvidados + Recursos Sin Tags */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '14px' }}>
                  <div className="dashboard-card glass">
                    <div className="card-header"><span className="card-title">📸 Snapshots de Disco Acumulados</span><span className="badge badge-warning">Costo de Almacenamiento</span></div>
                    <div className="custom-table-container">
                      <table className="custom-table">
                        <thead><tr><th>Nombre</th><th>Resource Group</th><th>GB</th><th>Región</th></tr></thead>
                        <tbody>
                          {(finopsReport?.old_snapshots || []).length > 0 ? (finopsReport!.old_snapshots.map((s, i) => (
                            <tr key={i}><td style={{ fontWeight: 600 }}>{s.name}</td><td>{s.resourceGroup}</td><td>{s.sizeGB || '?'} GB</td><td><code>{s.location}</code></td></tr>
                          ))) : <tr><td colSpan={4} style={{ textAlign: 'center', padding: '14px', color: 'var(--success)' }}>✅ Sin snapshots huérfanos</td></tr>}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  <div className="dashboard-card glass">
                    <div className="card-header"><span className="card-title">🏷️ Recursos Sin Ningún Tag (Punto Ciego de Costos)</span><span className="badge badge-danger">Sin Cost Allocation</span></div>
                    <div className="custom-table-container">
                      <table className="custom-table">
                        <thead><tr><th>Nombre</th><th>Tipo</th><th>Resource Group</th></tr></thead>
                        <tbody>
                          {(finopsReport?.untagged_resources || []).length > 0 ? (finopsReport!.untagged_resources.map((r, i) => (
                            <tr key={i}><td style={{ fontWeight: 600 }}>{r.name}</td><td style={{ fontSize: '0.75rem' }}>{r.type?.split('/').pop()}</td><td>{r.resourceGroup}</td></tr>
                          ))) : <tr><td colSpan={3} style={{ textAlign: 'center', padding: '14px', color: 'var(--success)' }}>✅ Todos los recursos tienen tags</td></tr>}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>

                <div className="section-head">
                  <span className="section-title">Atribución del gasto</span>
                  <span className="section-desc">A qué unidad de negocio pertenece cada peso, según las tags, y qué parte del gasto no se puede atribuir a nadie.</span>
                </div>
                {/* Distribución por Resource Group & Showback / Chargeback (2 columns) */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '14px' }}>
                  {/* Left: Showback / Chargeback por tags de negocio */}
                  <div className="dashboard-card glass">
                    <div className="card-header">
                      <span className="card-title">📂 Showback por unidad de negocio</span>
                      {finopsReport?.insights?.showback_status === 'partial' && (
                        <span className="badge badge-warning">Cobertura parcial</span>
                      )}
                    </div>
                    <div className="custom-table-container">
                      <table className="custom-table">
                        <thead><tr><th>Dimensión</th><th>Valor</th><th style={{ textAlign: 'right' }}>Gasto mensual</th></tr></thead>
                        <tbody>
                          {finopsReport?.insights?.showback_chargeback && finopsReport.insights.showback_chargeback.length > 0 ? (
                            finopsReport.insights.showback_chargeback.slice(0, 12).map((sb: any, i: number) => (
                              <tr key={i}>
                                <td><span className="badge badge-info">{sb.dimension}</span></td>
                                <td><strong style={{ color: '#fff' }}>{sb.value}</strong></td>
                                <td style={{ textAlign: 'right', color: 'var(--success)', fontWeight: 700 }}>
                                  ${Number(sb.monthly_cost_usd ?? 0).toFixed(2)}
                                </td>
                              </tr>
                            ))
                          ) : (
                            <tr><td colSpan={3} style={{ textAlign: 'center', padding: '14px', color: 'var(--text-secondary)' }}>
                              Sin gasto atribuible: hace falta cobertura de Cost Management sobre las suscripciones seleccionadas.
                            </td></tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {/* Right: Budgets por tags de negocio */}
                  <div className="dashboard-card glass">
                    <div className="card-header"><span className="card-title">📊 Presupuestos Consumidos por Scope</span><span className="badge badge-warning">Límites</span></div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginTop: '12px' }}>
                      {finopsReport?.insights?.budgets && finopsReport.insights.budgets.length > 0 ? (
                        finopsReport.insights.budgets.slice(0, 4).map((bg: any, i: number) => (
                          <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem' }}>
                              <span>Scope: <strong>{bg.scope}</strong></span>
                              <span style={{ fontWeight: 700 }}>${Number(bg.current_spending ?? 0).toFixed(2)} / ${Number(bg.budget_limit ?? 0).toFixed(2)} USD</span>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                              <div style={{ flex: 1, height: '8px', borderRadius: '4px', backgroundColor: 'rgba(255,255,255,0.07)', overflow: 'hidden' }}>
                                <div style={{ width: `${Math.min(100, bg.percentage_used)}%`, height: '100%', background: bg.percentage_used > 90 ? 'var(--danger)' : 'linear-gradient(90deg, var(--primary), var(--accent))', borderRadius: '4px' }} />
                              </div>
                              <span style={{ fontSize: '0.72rem', color: bg.percentage_used > 90 ? 'var(--danger)' : 'var(--text-secondary)' }}>{bg.percentage_used}%</span>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div style={{ textAlign: 'center', padding: '14px', color: 'var(--text-secondary)' }}>Cargando presupuestos...</div>
                      )}
                    </div>
                  </div>
                </div>

                {/* Anomalías de Costos de Azure Cost Management */}
                <div className="dashboard-card glass">
                  <div className="card-header"><span className="card-title">⚠️ Alertas y Detección de Anomalías de Costos (Azure Cost Management)</span><span className="badge badge-danger">Inteligencia FinOps</span></div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '12px' }}>
                    {finopsReport?.insights?.anomalies?.map((an: any, i: number) => (
                      <div key={i} style={{ display: 'flex', gap: '1rem', alignItems: 'flex-start', padding: '12px', borderRadius: '8px', background: 'rgba(255,255,255,0.015)', border: '1px solid rgba(255,255,255,0.05)' }}>
                        <span style={{ fontSize: '1.5rem' }}>🚨</span>
                        <div>
                          <strong style={{ color: '#fff', fontSize: '0.85rem' }}>{an.title}</strong>
                          <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', margin: '4px 0' }}>{an.description}</p>
                          <span style={{ fontSize: '0.72rem', color: 'var(--accent)', fontWeight: 600 }}>Acción sugerida: {an.recomm_action}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="section-head">
                  <span className="section-title">Optimización de tarifa y uso</span>
                  <span className="section-desc">Lo que no se elimina, pero se paga de más: máquinas encendidas fuera de horario, recursos sobredimensionados y compromisos de tarifa sin aprovechar.</span>
                </div>
                {/* Dev/QA encendidos fuera de horario & Recursos bajo uso y alto costo (2 columns) */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '14px' }}>
                  {/* Left: Dev/QA VMs running outside hours */}
                  <div className="dashboard-card glass">
                    <div className="card-header"><span className="card-title">⏰ VMs de Dev/QA encendidas fuera de horario</span><span className="badge badge-danger">Apagado Programable</span></div>
                    <div className="custom-table-container">
                      <table className="custom-table">
                        <thead><tr><th>VM</th><th>Ambiente</th><th>RG</th><th>Ahorro Est.</th></tr></thead>
                        <tbody>
                          {finopsReport?.insights?.running_dev_vms_outside_hours && finopsReport.insights.running_dev_vms_outside_hours.length > 0 ? (
                            finopsReport.insights.running_dev_vms_outside_hours.map((vm: any, i: number) => (
                              <tr key={i}>
                                <td style={{ fontWeight: 600 }}>{vm.name}</td>
                                <td><span className="badge badge-warning">{vm.environment}</span></td>
                                <td>{vm.resourceGroup}</td>
                                <td style={{ color: 'var(--success)', fontWeight: 700 }}>${Number(vm.saving_potential ?? 0).toFixed(2)} USD/mes</td>
                              </tr>
                            ))
                          ) : (
                            <tr><td colSpan={4} style={{ textAlign: 'center', padding: '14px', color: 'var(--success)' }}>✅ Todas las VMs Dev/QA respetan horarios de apagado</td></tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {/* Right: Underutilized resources CPU < 5% */}
                  <div className="dashboard-card glass">
                    <div className="card-header"><span className="card-title">📉 Recursos con bajo uso pero alto costo</span><span className="badge badge-warning">Right-sizing</span></div>
                    <div className="custom-table-container">
                      <table className="custom-table">
                        <thead><tr><th>VM</th><th>Tamaño</th><th>Uso CPU</th><th>Costo</th></tr></thead>
                        <tbody>
                          {finopsReport?.insights?.underutilized_resources && finopsReport.insights.underutilized_resources.length > 0 ? (
                            finopsReport.insights.underutilized_resources.map((ur: any, i: number) => (
                              <tr key={i}>
                                <td style={{ fontWeight: 600 }}>{ur.name}</td>
                                <td><code>{ur.size}</code></td>
                                <td style={{ color: 'var(--danger)', fontWeight: 700 }}>{ur.avg_cpu_percentage}% avg</td>
                                <td style={{ color: 'var(--warning)', fontWeight: 700 }}>${Number(ur.monthly_cost_usd ?? 0).toFixed(2)}/mes</td>
                              </tr>
                            ))
                          ) : (
                            <tr><td colSpan={4} style={{ textAlign: 'center', padding: '14px', color: 'var(--success)' }}>✅ Sin recursos sobredimensionados</td></tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>

                {/* Reservations suggestions & aging of resources without ExpirationDate (2 columns) */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '14px' }}>
                  {/* Left: Reservations recommendations */}
                  <div className="dashboard-card glass">
                    <div className="card-header"><span className="card-title">💡 Recomendaciones de Reservations & Savings Plans</span><span className="badge badge-success">Optimización de Tarifa</span></div>
                    <div className="custom-table-container">
                      <table className="custom-table">
                        <thead><tr><th>Tipo</th><th>SKU Size</th><th>Instancias</th><th>Opción</th><th>Ahorro Est.</th></tr></thead>
                        <tbody>
                          {finopsReport?.insights?.reservation_recommendations && finopsReport.insights.reservation_recommendations.length > 0 ? (
                            finopsReport.insights.reservation_recommendations.map((rs: any, i: number) => (
                              <tr key={i}>
                                <td>{rs.resource_type}</td>
                                <td><code>{rs.sku_size}</code></td>
                                <td style={{ textAlign: 'center' }}>{rs.quantity_instances}</td>
                                <td><span className="badge badge-info">{rs.savings_plan_option}</span></td>
                                <td style={{ color: 'var(--success)', fontWeight: 700 }}>{rs.estimated_savings_percentage}% (-${rs.monthly_saving_usd})</td>
                              </tr>
                            ))
                          ) : (
                            <tr><td colSpan={5} style={{ textAlign: 'center', padding: '14px', color: 'var(--text-secondary)' }}>Sin recomendaciones de tarifas aplicables</td></tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {/* Right: Aging Dev/QA resources with no ExpirationDate tag */}
                  <div className="dashboard-card glass">
                    <div className="card-header"><span className="card-title">📅 Aging de recursos temporales sin ExpirationDate</span><span className="badge badge-danger">Riesgo de Abandono</span></div>
                    <div className="custom-table-container">
                      <table className="custom-table">
                        <thead><tr><th>Recurso</th><th>Tipo</th><th>Resource Group</th></tr></thead>
                        <tbody>
                          {finopsReport?.insights?.aging_resources_no_expiration && finopsReport.insights.aging_resources_no_expiration.length > 0 ? (
                            finopsReport.insights.aging_resources_no_expiration.map((ag: any, i: number) => (
                              <tr key={i}>
                                <td style={{ fontWeight: 600 }}>{ag.name}</td>
                                <td><span className="badge badge-secondary">{ag.type}</span></td>
                                <td>{ag.resourceGroup}</td>
                              </tr>
                            ))
                          ) : (
                            <tr><td colSpan={3} style={{ textAlign: 'center', padding: '14px', color: 'var(--success)' }}>✅ Todos los recursos temporales tienen fecha de expiración</td></tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>

            </div>
            </SectionBoundary>
          )}

          {/* Active View: SecOps & Salud - FULL SCOPE */}
          {activeTab === 'secops' && (
            <SectionBoundary name="SecOps">
            <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

                {/* Exposición priorizada: severidad + gasto del recurso expuesto */}
                <div className="dashboard-card glass">
                  <div className="card-header" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '14px', marginBottom: '16px' }}>
                    <span className="card-title" style={{ fontSize: '1.05rem', display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <span style={{ fontSize: '1.4rem' }}>🎯</span> Exposición priorizada
                    </span>
                    {riskExposure && (
                      <span className={`badge ${riskExposure.coverage.uncovered_count > 0 ? 'badge-warning' : 'badge-success'}`}>
                        {riskExposure.coverage.covered_count} de {riskExposure.coverage.covered_count + riskExposure.coverage.uncovered_count} suscripciones con costo
                      </span>
                    )}
                  </div>

                  <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', lineHeight: 1.6, marginBottom: '14px' }}>
                    La severidad dice qué tan alcanzable es algo; el gasto, cuánto vale. Aquí la
                    severidad manda y el dinero desempata, para que un storage público de miles de
                    dólares al mes no se vea igual de urgente que uno de tres.
                  </div>

                  {!riskExposure ? (
                    <div style={{ padding: '14px 4px', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                      Consultando la exposición…
                    </div>
                  ) : (
                    <>
                      <div className="metric-strip" style={{ marginBottom: '14px' }}>
                        <div>
                          <div className="metric-value" style={{ color: 'var(--danger)' }}>
                            ${Number(riskExposure.totals?.monthly_usd_at_risk ?? 0).toLocaleString('es-CO', { maximumFractionDigits: 0 })}
                          </div>
                          <div className="metric-label">gasto mensual expuesto (facturado)</div>
                        </div>
                        <div>
                          <div className="metric-value">{riskExposure.totals.affected_resources}</div>
                          <div className="metric-label">recursos afectados</div>
                        </div>
                        <div>
                          <div className="metric-value" style={{ color: 'var(--warning)' }}>
                            {riskExposure.totals.unmeasured_resources}
                          </div>
                          <div className="metric-label">sin costo conocido (no son cero)</div>
                        </div>
                      </div>

                      <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '14px' }}>
                        {riskExposure.coverage.message}
                      </div>

                      {riskExposure.top_exposure.length > 0 && (
                        <div className="custom-table-container">
                          <table className="custom-table">
                            <thead>
                              <tr>
                                <th>Recurso</th>
                                <th>Tipo</th>
                                <th>Severidad</th>
                                <th style={{ textAlign: 'center' }}>Hallazgos</th>
                                <th style={{ textAlign: 'right' }}>Gasto expuesto</th>
                              </tr>
                            </thead>
                            <tbody>
                              {riskExposure.top_exposure.map((e) => (
                                <tr key={e.id}>
                                  <td><strong style={{ color: '#fff' }}>{e.name}</strong></td>
                                  <td><code style={{ fontSize: '0.75rem' }}>{e.tipo}</code></td>
                                  <td>
                                    <span className={`badge ${e.severidad === 'critica' ? 'badge-danger' : e.severidad === 'alta' ? 'badge-warning' : 'badge-info'}`}>
                                      {e.severidad}
                                    </span>
                                  </td>
                                  <td style={{ textAlign: 'center' }}>{e.hallazgos}</td>
                                  <td style={{ textAlign: 'right', color: 'var(--danger)', fontWeight: 700 }}>
                                    ${Number(e.monthly_cost_usd ?? 0).toLocaleString('es-CO', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}/mes
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}

                      {riskExposure.top_exposure.length === 0 && (
                        <div style={{ padding: '12px 4px', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                          Ningún recurso afectado tiene gasto facturado disponible, así que los
                          hallazgos van ordenados solo por severidad.
                        </div>
                      )}
                    </>
                  )}
                </div>

                {/* Risk Summary Header */}
                <div className="dashboard-card glass">
                  <div className="card-header" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '14px', marginBottom: '16px' }}>
                    <span className="card-title" style={{ fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <span style={{ fontSize: '1.5rem' }}>🛡️</span> Reporte Completo de Seguridad y Salud Operativa
                    </span>
                    <span className="badge badge-danger" style={{ padding: '6px 14px', fontSize: '0.9rem' }}>
                      Superficie de Ataque Activa
                    </span>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '12px' }}>
                    {[
                      { label: 'NSGs Expuestos', val: secopsReport?.exposed_nsgs?.length || 0, icon: '🚨', color: 'var(--danger)', sev: 'CRÍTICO' },
                      { label: 'Storage Público', val: secopsReport?.public_storage_accounts?.length || 0, icon: '🗄️', color: 'var(--danger)', sev: 'ALTO' },
                      { label: 'Key Vaults Expuestos', val: secopsReport?.exposed_keyvaults?.length || 0, icon: '🔑', color: 'var(--warning)', sev: 'ALTO' },
                      { label: 'IPs Públicas Activas', val: secopsReport?.public_ips_active?.length || 0, icon: '🌐', color: 'var(--accent)', sev: 'MEDIO' },
                      { label: 'Recursos Fallidos', val: secopsReport?.failed_resources?.length || 0, icon: '❌', color: 'var(--warning)', sev: 'MEDIO' },
                    ].map(({ label, val, icon, color, sev }) => (
                      <div key={label} className="stat-card" style={{ background: 'rgba(255,255,255,0.025)', padding: '14px', textAlign: 'center', borderRadius: '10px', border: `1px solid ${val > 0 ? color + '33' : 'rgba(255,255,255,0.06)'}` }}>
                        <div style={{ fontSize: '1.6rem', marginBottom: '4px' }}>{icon}</div>
                        <div className="stat-value" style={{ color: val > 0 ? color : 'var(--success)', fontSize: '1.6rem' }}>{val}</div>
                        <div className="stat-label" style={{ fontSize: '0.68rem', marginTop: '2px' }}>{label}</div>
                        {val > 0 && <div style={{ fontSize: '0.62rem', marginTop: '3px', color: color, fontWeight: 700 }}>{sev}</div>}
                      </div>
                    ))}
                  </div>
                </div>

                {/* Grid Row: Security Posture Breakdown & Chatbot */}
                <div className="dashboard-sections" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '14px' }}>
                  {/* Left Card: Severity breakdown */}
                  <div className="dashboard-card glass" style={{ maxHeight: '420px', overflowY: 'auto' }}>
                    <div className="card-header" style={{ position: 'sticky', top: 0, background: '#121826', zIndex: 10 }}>
                      <span className="card-title">📊 Resumen de Postura de Seguridad por Criticidad</span>
                      <span className="badge badge-info">Postura</span>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginTop: '12px', padding: '0 10px 10px 10px' }}>
                      {[
                        { label: 'Riesgos Críticos (NSGs Expuestos / SSH / RDP)', val: secopsReport?.exposed_nsgs?.length || 0, color: 'var(--danger)', description: 'Requiere remediación inmediata. Puertos administrativos abiertos a todo internet.' },
                        { label: 'Riesgos Altos (Storage Público / Key Vaults Expuestos)', val: (secopsReport?.public_storage_accounts?.length || 0) + (secopsReport?.exposed_keyvaults?.length || 0), color: '#f59e0b', description: 'Acceso de red público habilitado en almacenes de datos o llaves.' },
                        { label: 'Riesgos Medios (IPs Públicas en Uso / Failed)', val: (secopsReport?.public_ips_active?.length || 0) + (secopsReport?.failed_resources?.length || 0), color: 'var(--accent)', description: 'IPs públicas en uso o recursos con problemas operativos.' },
                      ].map(({ label, val, color, description }) => {
                        const total = (secopsReport?.exposed_nsgs?.length || 0) + (secopsReport?.public_storage_accounts?.length || 0) + (secopsReport?.exposed_keyvaults?.length || 0) + (secopsReport?.public_ips_active?.length || 0) + (secopsReport?.failed_resources?.length || 0);
                        const pct = total > 0 ? (val / total * 100).toFixed(0) : 0;
                        return (
                          <div key={label} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                              <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#fff' }}>{label}</span>
                              <span style={{ color: val > 0 ? color : 'var(--success)', fontWeight: 700, fontSize: '0.9rem' }}>{val} detectados</span>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                              <div style={{ flex: 1, height: '8px', borderRadius: '4px', backgroundColor: 'rgba(255,255,255,0.07)', overflow: 'hidden' }}>
                                <div style={{ width: `${pct}%`, height: '100%', backgroundColor: color, borderRadius: '4px' }} />
                              </div>
                              <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', minWidth: '30px', textAlign: 'right' }}>{pct}%</span>
                            </div>
                            <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>{description}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                </div>

                <div className="section-head">
                  <span className="section-title">Hallazgos por categoría</span>
                  <span className="section-desc">El detalle de cada regla, cuenta y almacén señalado, con la acción concreta para cerrarlo.</span>
                </div>
                {/* NSGs Expuestos */}
                <div className="dashboard-card glass">
                  <div className="card-header"><span className="card-title">🚨 NSGs con Puertos Admin Abiertos a Internet</span><span className="badge badge-danger">CRÍTICO — Riesgo de Acceso No Autorizado</span></div>
                  <div className="custom-table-container">
                    <table className="custom-table">
                      <thead><tr><th>NSG</th><th>Resource Group</th><th>Puerto</th><th>Origen</th><th>Regla</th><th>Severidad</th><th>Acción</th></tr></thead>
                      <tbody>
                        {(secopsReport?.exposed_nsgs || []).length > 0 ? (secopsReport!.exposed_nsgs.map((n, i) => {
                          const port = String(n.port || '');
                          const sev = port === '22' || port === '3389' ? 'CRÍTICO' : port === '*' ? 'CRÍTICO' : 'ALTO';
                          return (
                            <tr key={i}>
                              <td style={{ fontWeight: 600 }}>{n.name}</td><td>{n.resourceGroup}</td>
                              <td><span className="badge badge-danger">{port || '*'}</span></td>
                              <td><code style={{ color: 'var(--danger)' }}>{n.source || '*'}</code></td>
                              <td style={{ fontSize: '0.75rem' }}>{n.ruleName}</td>
                              <td><span className="badge badge-danger">{sev}</span></td>
                              <td><button className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '0.72rem' }} onClick={() => askAgent('secops', `El NSG ${n.name} tiene el puerto ${port || 'todos'} abierto desde ${n.source || '*'}. Dame los comandos exactos de Azure CLI para restringir esta regla y el procedimiento de remediación paso a paso.`)}>Remediar →</button></td>
                            </tr>
                          );
                        })) : <tr><td colSpan={7} style={{ textAlign: 'center', padding: '16px', color: 'var(--success)' }}>✅ Sin puertos de admin expuestos</td></tr>}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Storage Público + Key Vaults (2 columnas) */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '14px' }}>
                  <div className="dashboard-card glass">
                    <div className="card-header"><span className="card-title">🗄️ Storage Accounts con Acceso Público</span><span className="badge badge-danger">Exposición de Datos</span></div>
                    <div className="custom-table-container">
                      <table className="custom-table">
                        <thead><tr><th>Storage Account</th><th>Acceso Red</th><th>Acceso Blobs</th><th>Región</th><th>Acción</th></tr></thead>
                        <tbody>
                          {(secopsReport?.public_storage_accounts || []).length > 0 ? (secopsReport!.public_storage_accounts.map((s, i) => (
                            <tr key={i}><td style={{ fontWeight: 600 }}>{s.name}</td>
                              <td><span className={`badge ${s.publicNetworkAccess === 'Disabled' ? 'badge-success' : 'badge-danger'}`} style={{ fontSize: '0.7rem' }}>{s.publicNetworkAccess === 'Disabled' ? 'Restringido' : 'Público'}</span></td>
                              <td><span className={`badge ${s.allowBlobPublicAccess === 'true' ? 'badge-danger' : 'badge-success'}`} style={{ fontSize: '0.7rem' }}>{s.allowBlobPublicAccess === 'true' ? 'Habilitado' : 'Deshabilitado'}</span></td>
                              <td><code>{s.location}</code></td>
                              <td><button className="btn btn-secondary" style={{ padding: '3px 6px', fontSize: '0.72rem' }} onClick={() => askAgent('secops', `El storage account ${s.name} tiene Acceso de Red establecido en "${s.publicNetworkAccess || 'Enabled'}" y Acceso Público a Blobs en "${s.allowBlobPublicAccess || 'false'}". ¿Cuál es el riesgo de seguridad de esta configuración y qué comandos CLI uso para remediarlo?`)}>Analizar</button></td></tr>
                          ))) : <tr><td colSpan={5} style={{ textAlign: 'center', padding: '14px', color: 'var(--success)' }}>✅ Sin storage público</td></tr>}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  <div className="dashboard-card glass">
                    <div className="card-header"><span className="card-title">🔑 Key Vaults con Acceso Público</span><span className="badge badge-warning">Riesgo de Secretos</span></div>
                    <div className="custom-table-container">
                      <table className="custom-table">
                        <thead><tr><th>Key Vault</th><th>Resource Group</th><th>Acceso Público</th><th>Región</th><th>Acción</th></tr></thead>
                        <tbody>
                          {(secopsReport?.exposed_keyvaults || []).length > 0 ? (secopsReport!.exposed_keyvaults.map((k, i) => (
                            <tr key={i}><td style={{ fontWeight: 600 }}>{k.name}</td><td>{k.resourceGroup}</td>
                              <td><span className="badge badge-danger">{k.publicNetworkAccess || 'Enabled'}</span></td>
                              <td><code>{k.location}</code></td>
                              <td><button className="btn btn-secondary" style={{ padding: '3px 6px', fontSize: '0.72rem' }} onClick={() => askAgent('secops', `El Key Vault ${k.name} tiene acceso público habilitado. ¿Cómo configuro un private endpoint y deshabilito el acceso público?`)}>Analizar</button></td></tr>
                          ))) : <tr><td colSpan={5} style={{ textAlign: 'center', padding: '14px', color: 'var(--success)' }}>✅ Sin Key Vaults con acceso público</td></tr>}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>

                {/* IPs Públicas Activas (Superficie de Ataque) + VMs sin Encryption */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '14px' }}>
                  <div className="dashboard-card glass">
                    <div className="card-header"><span className="card-title">🌐 IPs Públicas Activas (Superficie de Ataque)</span><span className="badge badge-warning">Exposición a Internet</span></div>
                    <div className="custom-table-container">
                      <table className="custom-table">
                        <thead><tr><th>Nombre</th><th>IP Address</th><th>SKU</th><th>Región</th></tr></thead>
                        <tbody>
                          {(secopsReport?.public_ips_active || []).length > 0 ? (secopsReport!.public_ips_active.map((ip, i) => (
                            <tr key={i}><td style={{ fontWeight: 600 }}>{ip.name}</td>
                              <td><code style={{ color: 'var(--accent)' }}>{ip.ipAddress}</code></td>
                              <td><span className="badge badge-info">{ip.sku || 'Standard'}</span></td>
                              <td><code>{ip.location}</code></td></tr>
                          ))) : <tr><td colSpan={4} style={{ textAlign: 'center', padding: '14px', color: 'var(--success)' }}>✅ Sin IPs públicas activas</td></tr>}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  <div className="dashboard-card glass">
                    <div className="card-header"><span className="card-title">🖥️ VMs sin Disk Encryption</span><span className="badge badge-danger">Compliance Risk</span></div>
                    <div className="custom-table-container">
                      <table className="custom-table">
                        <thead><tr><th>VM</th><th>Resource Group</th><th>Región</th><th>Acción</th></tr></thead>
                        <tbody>
                          {(secopsReport?.vms_without_encryption || []).length > 0 ? (secopsReport!.vms_without_encryption.map((v, i) => (
                            <tr key={i}><td style={{ fontWeight: 600 }}>{v.name}</td><td>{v.resourceGroup}</td><td><code>{v.location}</code></td>
                              <td><button className="btn btn-secondary" style={{ padding: '3px 6px', fontSize: '0.72rem' }} onClick={() => askAgent('secops', `La VM ${v.name} no tiene disk encryption habilitado. ¿Cómo habilito Azure Disk Encryption y cuáles son los pasos?`)}>Ver</button></td></tr>
                          ))) : <tr><td colSpan={4} style={{ textAlign: 'center', padding: '14px', color: 'var(--success)' }}>✅ Todas las VMs tienen encryption</td></tr>}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>

                {/* Recursos en Estado Fallido */}
                <div className="dashboard-card glass">
                  <div className="card-header"><span className="card-title">❌ Recursos con provisioningState = Failed</span><span className="badge badge-warning">Salud Operativa</span></div>
                  <div className="custom-table-container">
                    <table className="custom-table">
                      <thead><tr><th>Nombre</th><th>Tipo de Recurso</th><th>Resource Group</th><th>Región</th><th>Diagnóstico</th></tr></thead>
                      <tbody>
                        {(secopsReport?.failed_resources || []).length > 0 ? (secopsReport!.failed_resources.map((f, i) => (
                          <tr key={i}><td style={{ fontWeight: 600 }}>{f.name}</td>
                            <td style={{ fontSize: '0.75rem' }}>{f.type?.split('/').pop()}</td>
                            <td>{f.resourceGroup}</td><td><code>{f.location}</code></td>
                            <td><button className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '0.72rem' }} onClick={() => askAgent('secops', `El recurso ${f.name} de tipo ${f.type} está en estado Failed. ¿Cuáles son las causas más comunes y cómo lo diagnostico y remedío?`)}>Diagnosticar →</button></td></tr>
                        ))) : <tr><td colSpan={5} style={{ textAlign: 'center', padding: '16px', color: 'var(--success)' }}>✅ No hay recursos en estado fallido</td></tr>}
                      </tbody>
                    </table>
                  </div>
                </div>

            </div>
            </SectionBoundary>
          )}



          {/* Active View: IaC & Terraform */}
          {activeTab === 'iac' && (
            <SectionBoundary name="Infraestructura como código">
            <div className="recommendations-container animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              
              <div className="section-head">
                <span className="section-title">Cobertura de infraestructura como código</span>
                <span className="section-desc">Cuánto del inventario declara la herramienta que lo creó. La ausencia de marca no prueba que algo se hiciera a mano: es ausencia de rastro.</span>
              </div>
              {/* KPIs Header */}
              <div className="dashboard-grid">
                <div className="dashboard-card glass">
                  <div className="card-header">
                    <span className="card-title">Sin marca de IaC</span>
                  </div>
                  <div className="card-value" style={{ color: 'var(--accent)' }}>
                    {stats ? stats.portal_managed : 0}
                  </div>
                  <div className="card-meta">
                    Recursos sin ninguna tag que declare la herramienta que los creó. Mide
                    etiquetado, no cobertura: para saber qué está realmente codificado, mira
                    la tarjeta de al lado.
                  </div>
                </div>

                <div className="dashboard-card glass">
                  <div className="card-header">
                    <span className="card-title">Total Recursos Suscripción</span>
                  </div>
                  <div className="card-value">
                    {stats ? stats.total_resources : 0}
                  </div>
                  <div className="card-meta">Total de activos bajo monitoreo</div>
                </div>

                <div className="dashboard-card glass">
                  <div className="card-header">
                    <span className="card-title">Gestionado por Terraform</span>
                    {tfCoverage?.available && (
                      <span className="badge badge-success">Verificado en el estado</span>
                    )}
                  </div>
                  <div className="card-value" style={{ color: 'var(--success)' }}>
                    {tfCoverage?.available ? `${tfCoverage.coverage_percentage.toFixed(1)}%` : '—'}
                  </div>
                  <div className="card-meta">
                    {tfCoverage?.available
                      ? `${tfCoverage.managed_in_inventory.toLocaleString('es-CO')} de ${tfCoverage.total_resources.toLocaleString('es-CO')} recursos aparecen en un estado de Terraform. Esto no es una etiqueta: es el estado real.`
                      : (tfCoverage?.message || 'Leyendo los estados de Terraform…')}
                  </div>
                </div>
              </div>

              {tfCoverage?.available && (
                <div className="dashboard-card glass">
                  <div className="card-header">
                    <span className="card-title">📖 Estados de Terraform leídos</span>
                    <span className="badge badge-info">
                      {tfCoverage.states_read} leído{tfCoverage.states_read === 1 ? '' : 's'}
                      {tfCoverage.states_failed > 0 ? ` · ${tfCoverage.states_failed} con error` : ''}
                    </span>
                  </div>

                  <div className="metric-strip" style={{ marginBottom: '14px' }}>
                    <div>
                      <div className="metric-value" style={{ color: 'var(--success)' }}>
                        {tfCoverage.managed_ids_total.toLocaleString('es-CO')}
                      </div>
                      <div className="metric-label">recursos en los estados</div>
                    </div>
                    <div>
                      <div className="metric-value">{tfCoverage.unmanaged_count.toLocaleString('es-CO')}</div>
                      <div className="metric-label">sin estado que los gestione</div>
                    </div>
                    <div>
                      <div className="metric-value" style={{ color: 'var(--warning)' }}>
                        {tfCoverage.stale_ids.toLocaleString('es-CO')}
                      </div>
                      <div className="metric-label">en el estado pero ya no existen</div>
                    </div>
                  </div>

                  <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', lineHeight: 1.6, marginBottom: '12px' }}>
                    {tfCoverage.message}
                    {tfCoverage.stale_ids > 0 && (
                      <> Los {tfCoverage.stale_ids} recursos que siguen en el estado y ya no existen
                      en Azure se borraron sin pasar por Terraform: el próximo <code>plan</code> va a
                      intentar recrearlos.</>
                    )}
                  </div>

                  <div className="custom-table-container">
                    <table className="custom-table">
                      <thead><tr><th>Estado</th><th style={{ textAlign: 'right' }}>Recursos</th></tr></thead>
                      <tbody>
                        {tfCoverage.states.filter(e => e.resources > 0 || !e.ok).slice(0, 20).map((e) => (
                          <tr key={e.name}>
                            <td><code style={{ fontSize: '0.74rem' }}>{e.name}</code></td>
                            <td style={{ textAlign: 'right', color: e.ok ? 'var(--text-primary)' : 'var(--danger)' }}>
                              {e.ok ? e.resources : (e.reason || 'error')}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              <div className="section-head">
                <span className="section-title">Evidencia de creación manual</span>
                <span className="section-desc">Quién creó cada recurso, según el historial de cambios de Azure. Esto sí lo demuestra, dentro de la ventana que Azure conserva.</span>
              </div>
              {/* Creaciones manuales con evidencia (resourcechanges) */}
              <div className="dashboard-card glass">
                <div className="card-header">
                  <span className="card-title">🔎 Creados a mano, con evidencia</span>
                  {manualCreations?.available && (
                    <span className="badge badge-info">
                      {manualCreations.windowFrom?.slice(0, 10)} → {manualCreations.windowTo?.slice(0, 10)}
                    </span>
                  )}
                </div>

                <div style={{ padding: '12px 4px', fontSize: '0.82rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                  El historial de cambios de Azure registra qué identidad creó cada recurso. Una
                  cuenta de persona significa portal o CLI; un service principal, automatización.
                  Azure conserva esos eventos unos catorce días, así que esto cubre lo reciente y
                  nunca el inventario histórico.
                </div>

                {!manualCreations?.available ? (
                  <div style={{ padding: '14px 4px', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                    No hay eventos de creación en la ventana que Azure conserva para las
                    suscripciones seleccionadas.
                  </div>
                ) : (
                  <>
                    <div className="metric-strip" style={{ marginBottom: '14px' }}>
                      <div>
                        <div className="metric-value" style={{ color: 'var(--danger)' }}>{manualCreations.manualCount}</div>
                        <div className="metric-label">creados por una persona</div>
                      </div>
                      <div>
                        <div className="metric-value" style={{ color: 'var(--success)' }}>{manualCreations.automatedCount}</div>
                        <div className="metric-label">creados por automatización</div>
                      </div>
                      <div>
                        <div className="metric-value">{manualCreations.totalCreations}</div>
                        <div className="metric-label">creaciones en la ventana</div>
                      </div>
                    </div>

                    {manualCreations.manualCreations.length > 0 && (
                      <div className="table-responsive">
                        <table className="table">
                          <thead>
                            <tr>
                              <th>Recurso</th>
                              <th>Tipo</th>
                              <th>Creado por</th>
                              <th>Cuándo</th>
                            </tr>
                          </thead>
                          <tbody>
                            {manualCreations.manualCreations.map((c) => (
                              <tr key={c.id}>
                                <td><strong>{c.name}</strong></td>
                                <td>
                                  <code style={{ fontSize: '0.75rem', padding: '2px 4px', background: 'rgba(255,255,255,0.04)', borderRadius: '4px', color: 'var(--text-secondary)' }}>
                                    {c.type ? c.type.split('/').slice(-2).join('/') : ''}
                                  </code>
                                </td>
                                <td>{c.createdBy}</td>
                                <td style={{ whiteSpace: 'nowrap' }}>
                                  {c.createdAt ? new Date(c.createdAt).toLocaleString('es-CO') : ''}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </>
                )}
              </div>

              <div className="section-head">
                <span className="section-title">Recursos por codificar</span>
                <span className="section-desc">Candidatos a llevar a Terraform, con el generador de HCL a un clic.</span>
              </div>
              {/* Shadow IT Resources List */}
              <div className="dashboard-card glass">
                <div className="card-header">
                  <span className="card-title">Inventario de Recursos Manuales (Shadow IT)</span>
                </div>
                <div className="table-responsive">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Nombre</th>
                        <th>Tipo de Recurso</th>
                        <th>Resource Group</th>
                        <th>Suscripción</th>
                        <th>Ubicación</th>
                        <th>Gobernanza</th>
                        <th style={{ textAlign: 'center' }}>Acción</th>
                      </tr>
                    </thead>
                    <tbody>
                      {manualResources.length > 0 ? (
                        manualResources.map((res, index) => (
                          <tr key={index}>
                            <td><strong>{res.name}</strong></td>
                            <td>
                              <code style={{ fontSize: '0.75rem', padding: '2px 4px', background: 'rgba(255,255,255,0.04)', borderRadius: '4px', color: 'var(--text-secondary)' }}>
                                {res.type ? res.type.split('/').slice(-2).join('/') : ''}
                              </code>
                            </td>
                            <td>{res.resourceGroup}</td>
                            <td><span style={{ fontSize: '0.8rem' }}>{res.subscription_name || 'Subscription'}</span></td>
                            <td>{res.location}</td>
                            <td>
                              <span className={`badge ${res.tagging_ok === 'Si' ? 'badge-success' : 'badge-danger'}`} style={{ fontSize: '0.7rem', padding: '2px 6px' }}>
                                {res.tagging_ok === 'Si' ? 'Tags Ok' : 'Faltan Tags'}
                              </span>
                            </td>
                            <td style={{ textAlign: 'center' }}>
                              <button 
                                className="btn btn-primary"
                                style={{ padding: '4px 10px', fontSize: '0.75rem', background: 'var(--accent)' }}
                                onClick={() => handleGenerateIaC(res)}
                              >
                                Codificar (IaC)
                              </button>
                            </td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={7} style={{ textAlign: 'center', padding: '20px 12px', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                            🎉 ¡Felicitaciones! Todos los recursos de la suscripción están bajo el control de Terraform.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Code Generation Modal */}
              {iacModalOpen && selectedResourceForIaC && (
                <div style={{
                  position: 'fixed',
                  top: 0,
                  left: 0,
                  right: 0,
                  bottom: 0,
                  background: 'rgba(10, 15, 30, 0.85)',
                  backdropFilter: 'blur(10px)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  zIndex: 1000,
                  padding: '20px'
                }}>
                  <div className="dashboard-card glass" style={{
                    width: '100%',
                    maxWidth: '900px',
                    maxHeight: '90vh',
                    display: 'flex',
                    flexDirection: 'column',
                    padding: '24px',
                    boxShadow: '0 20px 40px rgba(0,0,0,0.5)',
                    border: '1px solid rgba(255,255,255,0.1)'
                  }}>
                    {/* Modal Header */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '12px' }}>
                      <div>
                        <h3 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '1.2rem' }}>
                          Generador de Infraestructura como Código (IaC)
                        </h3>
                        <p style={{ margin: '4px 0 0 0', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                          Recurso: <code style={{ color: 'var(--accent)' }}>{selectedResourceForIaC.name}</code> | Tipo: <code>{selectedResourceForIaC.type}</code>
                        </p>
                      </div>
                      <button 
                        onClick={() => setIacModalOpen(false)}
                        style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', fontSize: '1.5rem', cursor: 'pointer' }}
                      >
                        &times;
                      </button>
                    </div>

                    {/* Modal Parameter Selectors */}
                    <div style={{ display: 'flex', gap: '1rem', marginBottom: '16px', background: 'rgba(255,255,255,0.02)', padding: '12px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.04)' }}>
                      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Entorno Destino (Folder)</label>
                        <select 
                          className="teams-input" 
                          style={{ padding: '6px', fontSize: '0.8rem', background: '#0a0f1e' }}
                          value={iacEnvironment}
                          onChange={(e) => handleRegenerateIaC(e.target.value as any, iacDomain)}
                        >
                          <option value="dev">dev</option>
                          <option value="qa">qa</option>
                          <option value="prod">prod</option>
                        </select>
                      </div>

                      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Dominio Técnico (Stack)</label>
                        <select 
                          className="teams-input" 
                          style={{ padding: '6px', fontSize: '0.8rem', background: '#0a0f1e' }}
                          value={iacDomain}
                          onChange={(e) => handleRegenerateIaC(iacEnvironment, e.target.value as any)}
                        >
                          <option value="networking">networking</option>
                          <option value="platform">platform</option>
                          <option value="data">data</option>
                          <option value="security">security</option>
                        </select>
                      </div>
                    </div>

                    {/* Modal Body / Loading State */}
                    {iacGenerating ? (
                      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '300px', gap: '1rem' }}>
                        <RefreshCw className="animate-spin" size={40} style={{ color: 'var(--accent)' }} />
                        <span style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>Generando configuración de Terraform y bloque import con Gemini...</span>
                      </div>
                    ) : generatedIaCFiles ? (
                      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: '300px' }}>
                        {/* File Tabs */}
                        <div style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.06)', marginBottom: '12px', gap: '4px', overflowX: 'auto' }}>
                          {(['main_tf', 'providers_tf', 'variables_tf', 'outputs_tf', 'terraform_tfvars', 'backend_hcl'] as const).map(tab => (
                            <button
                              key={tab}
                              onClick={() => setActiveIaCFileTab(tab)}
                              style={{
                                padding: '8px 12px',
                                fontSize: '0.8rem',
                                border: 'none',
                                background: activeIaCFileTab === tab ? 'rgba(255,255,255,0.06)' : 'none',
                                color: activeIaCFileTab === tab ? 'var(--accent)' : 'var(--text-secondary)',
                                borderBottom: activeIaCFileTab === tab ? '2px solid var(--accent)' : 'none',
                                cursor: 'pointer',
                                borderRadius: '4px 4px 0 0',
                                fontWeight: activeIaCFileTab === tab ? 'bold' : 'normal',
                                whiteSpace: 'nowrap'
                              }}
                            >
                              {tab.replace('_', '.')}
                            </button>
                          ))}
                        </div>

                        {/* Code Display Area */}
                        <div style={{ flex: 1, position: 'relative', overflowY: 'auto', background: '#050814', padding: '16px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.04)', maxHeight: '380px' }}>
                          <button
                            onClick={() => {
                              const codeMap = {
                                main_tf: generatedIaCFiles.main_tf,
                                providers_tf: generatedIaCFiles.providers_tf,
                                variables_tf: generatedIaCFiles.variables_tf,
                                outputs_tf: generatedIaCFiles.outputs_tf,
                                terraform_tfvars: generatedIaCFiles.terraform_tfvars,
                                backend_hcl: generatedIaCFiles.backend_hcl
                              };
                              copyToClipboard(codeMap[activeIaCFileTab] || '');
                            }}
                            className="btn btn-secondary"
                            style={{ position: 'absolute', top: '10px', right: '10px', padding: '4px 8px', fontSize: '0.7rem', display: 'flex', gap: '4px', alignItems: 'center' }}
                          >
                            <Copy size={12} /> Copiar
                          </button>
                          
                          <pre style={{ margin: 0, fontFamily: 'Fira Code, monospace', fontSize: '0.8rem', color: '#38ef7d', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                            {activeIaCFileTab === 'main_tf' && generatedIaCFiles.main_tf}
                            {activeIaCFileTab === 'providers_tf' && generatedIaCFiles.providers_tf}
                            {activeIaCFileTab === 'variables_tf' && generatedIaCFiles.variables_tf}
                            {activeIaCFileTab === 'outputs_tf' && generatedIaCFiles.outputs_tf}
                            {activeIaCFileTab === 'terraform_tfvars' && generatedIaCFiles.terraform_tfvars}
                            {activeIaCFileTab === 'backend_hcl' && generatedIaCFiles.backend_hcl}
                          </pre>
                        </div>

                        <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '8px', display: 'flex', justifyContent: 'space-between' }}>
                          <span>Modo de generación: <strong>{generatedIaCFiles.generation_mode === 'gemini_ai' ? 'Gemini Pro RAG' : 'Fallback Rules (Local Templates)'}</strong></span>
                          <span>Ubicación destino sugerida en repo: <code>stacks/{(selectedResourceForIaC.subscription_name || 'suscripcion').toLowerCase().replace(/[^a-z0-9]+/g, '-')}/{iacEnvironment}/{iacDomain}/</code></span>
                        </div>
                      </div>
                    ) : (
                      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '300px', color: 'var(--text-secondary)' }}>
                        Ocurrió un error al intentar generar la infraestructura.
                      </div>
                    )}

                    {/* Modal Footer */}
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '12px', marginTop: '16px' }}>
                      <button 
                        className="btn btn-secondary" 
                        onClick={() => setIacModalOpen(false)}
                        style={{ padding: '6px 14px', fontSize: '0.8rem' }}
                      >
                        Cerrar
                      </button>
                      <button 
                        className="btn btn-primary"
                        style={{ padding: '6px 14px', fontSize: '0.8rem', display: 'flex', gap: '4px', alignItems: 'center', opacity: 0.6, cursor: 'not-allowed' }}
                        disabled
                        title="La integración directa de Pull Requests se habilitará en la Fase 2."
                      >
                        Crear PR Automático (Fase 2)
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
            </SectionBoundary>
          )}


          {activeTab === 'iso' && (
            <SectionBoundary name="Gobernanza ISO 27001">
            <div className="recommendations-container animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              
              <div className="section-head">
                <span className="section-title">Clasificación de activos de información</span>
                <span className="section-desc">Confidencialidad, integridad y disponibilidad de cada recurso, con su puntuación de criticidad según ISO/IEC 27001:2022.</span>
              </div>
              {/* KPIs Header */}
              <div className="dashboard-grid">
                <div className="dashboard-card glass">
                  <div className="card-header">
                    <span className="card-title">Total Activos de Información</span>
                  </div>
                  <div className="card-value">
                    {isoReport?.stats?.total_assets || 0}
                  </div>
                  <div className="card-meta">Activos bajo inventario normativo</div>
                </div>

                <div className="dashboard-card glass">
                  <div className="card-header">
                    <span className="card-title">Activos Críticos / Confidenciales</span>
                  </div>
                  <div className="card-value" style={{ color: 'var(--danger)' }}>
                    {isoReport?.stats?.classification_distribution?.Confidencial || 0}
                  </div>
                  <div className="card-meta">Recursos con puntuación de criticidad alta</div>
                </div>

                <div className="dashboard-card glass">
                  <div className="card-header">
                    <span className="card-title">Puntuación Promedio de Criticidad</span>
                  </div>
                  <div className="card-value" style={{ color: 'var(--accent)' }}>
                    {isoReport?.stats?.average_criticality_score || 0} <span style={{ fontSize: '1rem', color: 'var(--text-secondary)' }}>/ 9</span>
                  </div>
                  <div className="card-meta">Promedio de triada C-I-D</div>
                </div>
              </div>

              {/* ISO 27001 Assets Table */}
              <div className="dashboard-card glass">
                <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span className="card-title">🛡️ Inventario de Activos Clasificados (ISO/IEC 27001:2022)</span>
                  <a 
                    className="btn btn-primary" 
                    style={{ fontSize: '0.75rem', padding: '6px 12px', background: 'var(--accent)' }}
                    href={`${API_URL}/api/inventory/download/Azure_IaC_Inventario.xlsx`}
                    download
                  >
                    Descargar Excel Maestro (Hoja 12)
                  </a>
                </div>
                
                <div className="table-responsive">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Nombre</th>
                        <th>Tipo</th>
                        <th>Clasificación</th>
                        <th>Custodio</th>
                        <th style={{ textAlign: 'center' }}>C - I - D</th>
                        <th style={{ textAlign: 'center' }}>Criticidad</th>
                        <th style={{ textAlign: 'center' }}>Gestión Riesgo</th>
                        <th>Suscripción</th>
                      </tr>
                    </thead>
                    <tbody>
                      {loadingIso ? (
                        <tr>
                          <td colSpan={8} style={{ textAlign: 'center', padding: '20px 12px', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                            <div className="flex justify-center items-center gap-2">
                              <span className="dot dot-success animate-ping"></span>
                              Cargando reporte de Gobernanza ISO 27001...
                            </div>
                          </td>
                        </tr>
                      ) : isoReport?.data && isoReport.data.length > 0 ? (
                        isoReport.data.map((item: any, index: number) => (
                          <tr key={index}>
                            <td><strong>{item.name}</strong></td>
                            <td>
                              <code style={{ fontSize: '0.75rem', padding: '2px 4px', background: 'rgba(255,255,255,0.04)', borderRadius: '4px' }}>
                                {item.resourceType}
                              </code>
                            </td>
                            <td>
                              <span className={`badge ${
                                item["Clasificación del activo"] === 'Confidencial' ? 'badge-danger' : 
                                item["Clasificación del activo"] === 'Restringido' ? 'badge-warning' : 'badge-success'
                              }`} style={{ fontSize: '0.7rem' }}>
                                {item["Clasificación del activo"]}
                              </span>
                            </td>
                            <td><code>{item.custodio}</code></td>
                            <td style={{ textAlign: 'center', fontFamily: 'monospace', fontSize: '0.85rem' }}>
                              C:{item.confidencialidad} | I:{item.integridad} | D:{item.disponibilidad}
                            </td>
                            <td style={{ textAlign: 'center' }}>
                              <strong style={{ 
                                color: item["puntuación del activo"] >= 8 ? 'var(--danger)' : 
                                       item["puntuación del activo"] >= 6 ? '#f59e0b' : 'var(--success-color)' 
                              }}>
                                {item["puntuación del activo"]}
                              </strong>
                            </td>
                            <td style={{ textAlign: 'center' }}>
                              <span className={`badge ${item["Gestión de riesgo (SI/NO)"] === 'SI' ? 'badge-danger' : 'badge-success'}`} style={{ fontSize: '0.7rem' }}>
                                {item["Gestión de riesgo (SI/NO)"]}
                              </span>
                            </td>
                            <td><span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{item.subscription}</span></td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={8} style={{ textAlign: 'center', padding: '20px 12px', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                            No hay datos ISO disponibles. Por favor, corre una sincronización del inventario para clasificar los recursos.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

            </div>
            </SectionBoundary>
          )}



        </div>
      </main>

      {/* Sync Log Modal Overlay */}
      {showSyncModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.85)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
          padding: '2rem'
        }}>
          <div className="glass" style={{
            width: '100%',
            maxWidth: '800px',
            borderRadius: '12px',
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            maxHeight: '85vh',
            boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)'
          }}>
            <div style={{
              padding: '1.25rem 1.5rem',
              borderBottom: '1px solid var(--border-color)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              backgroundColor: 'rgba(255,255,255,0.02)'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Terminal size={18} style={{ color: 'var(--primary)' }} />
                <h3 style={{ fontSize: '1rem', fontWeight: 600 }}>Logs de Extracción de Inventario</h3>
              </div>
              <button 
                className="btn btn-secondary" 
                style={{ padding: '4px 10px' }}
                onClick={() => {
                  setShowSyncModal(false);
                  fetchStats();
                  fetchResources();
                  fetchManualResources();
                }}
              >
                Cerrar Consola
              </button>
            </div>
            
            <div style={{
              flexGrow: 1,
              backgroundColor: '#05070c',
              padding: '1.5rem',
              overflowY: 'auto',
              fontFamily: 'monospace',
              fontSize: '0.85rem',
              color: '#34D399',
              lineHeight: 1.5,
              whiteSpace: 'pre-wrap',
              height: '350px'
            }}>
              {syncLogs}
              {syncRunning && (
                <div className="pulse" style={{ color: 'var(--warning)', marginTop: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <RefreshCw size={14} className="pulse" /> Ejecutando scripts semanales...
                </div>
              )}
              <div ref={logConsoleEndRef} />
            </div>

            <div style={{
              padding: '1rem 1.5rem',
              borderTop: '1px solid var(--border-color)',
              display: 'flex',
              justifyContent: 'flex-end',
              backgroundColor: 'rgba(255,255,255,0.01)',
              fontSize: '0.8rem',
              color: 'var(--text-secondary)'
            }}>
              <span>Presiona 'Cerrar Consola' para regresar; el script seguirá corriendo en segundo plano si es necesario.</span>
            </div>
          </div>
        </div>
      )}

      {/* Toast Notification */}
      {showCopyNotification && (
        <div style={{
          position: 'fixed',
          bottom: '24px',
          right: '24px',
          backgroundColor: 'var(--success)',
          color: 'white',
          padding: '10px 16px',
          borderRadius: '4px',
          fontSize: '0.85rem',
          boxShadow: 'var(--shadow-lg)',
          zIndex: 1001,
          animation: 'fadeIn 0.2s ease'
        }}>
          ✓ Copiado al portapapeles
        </div>
      )}

      {/* ====================================================================
          Consola de agentes
          ====================================================================
          Un solo lugar para los cuatro agentes, disponible desde cualquier
          sección. Antes cada pestaña incrustaba su propio chat: el mismo
          componente cuatro veces, partiendo en dos el ancho de trabajo, y para
          cambiar de agente había que cambiar de pestaña. Como panel lateral no
          desplaza el contenido y se cierra cuando estorba.
          ==================================================================== */}
      {!consoleOpen && (
        <button
          className="agent-dock-toggle"
          onClick={() => setConsoleOpen(true)}
          title="Abrir la consola de agentes"
        >
          <MessageSquare size={16} />
          <span>Agentes</span>
        </button>
      )}

      <aside className={`agent-dock ${consoleOpen ? 'is-open' : ''}`} aria-hidden={!consoleOpen}>
        <div className="agent-dock-head">
          <div className="agent-dock-tabs" role="tablist">
            {AGENTES.map((a) => (
              <button
                key={a.id}
                role="tab"
                aria-selected={consoleAgent === a.id}
                className={`agent-chip ${consoleAgent === a.id ? 'is-active' : ''}`}
                onClick={() => setConsoleAgent(a.id)}
                title={a.desc}
              >
                <span aria-hidden="true">{a.icon}</span>
                <span>{a.short}</span>
              </button>
            ))}
          </div>
          <button
            className="agent-dock-close"
            onClick={() => setConsoleOpen(false)}
            title="Cerrar la consola"
            aria-label="Cerrar la consola"
          >
            ×
          </button>
        </div>
        <div className="agent-dock-body">
          {consoleOpen && renderAgentChat(consoleAgent)}
        </div>
      </aside>

      {toastMessage && (
        <div style={{
          position: 'fixed',
          bottom: '24px',
          right: '24px',
          backgroundColor: toastType === 'success' ? 'var(--success)' : toastType === 'error' ? 'var(--danger, #ef4444)' : 'var(--primary)',
          color: 'white',
          padding: '10px 16px',
          borderRadius: '4px',
          fontSize: '0.85rem',
          boxShadow: 'var(--shadow-lg)',
          zIndex: 1001,
          animation: 'fadeIn 0.2s ease',
          display: 'flex',
          alignItems: 'center',
          gap: '8px'
        }}>
          {toastType === 'success' ? '✓' : toastType === 'error' ? '❌' : 'ℹ️'} {toastMessage}
        </div>
      )}
    </div>
  );
}

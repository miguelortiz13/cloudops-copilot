import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Ctx, type AgentType, type AppState, type Theme, type Toast } from './context';
import { get } from '../lib/api';
import type { CloudAccount, CloudAccounts, Me, Role, Subscription } from '../lib/types';

function readTheme(): Theme {
  try {
    const t = localStorage.getItem('theme');
    if (t === 'light' || t === 'dark' || t === 'system') return t;
  } catch {
    /* almacenamiento no disponible */
  }
  return 'system';
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [subscriptionsLoaded, setLoaded] = useState(false);
  const [accounts, setAccounts] = useState<CloudAccount[]>([]);
  const [providerLabels, setLabels] = useState<Record<string, string>>({ azure: 'Microsoft Azure' });
  const [selected, setSelected] = useState<string[]>([]);
  const [theme, setThemeState] = useState<Theme>(readTheme);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [dockOpen, setDockOpen] = useState(false);
  const [dockAgent, setDockAgent] = useState<AgentType>('inventory');
  const [pendingQuestion, setPending] = useState<AppState['pendingQuestion']>(null);
  const [me, setMe] = useState<Me | null>(null);
  const toastId = useRef(0);

  useEffect(() => {
    // Cuentas de todas las nubes (de la base) y, para las vistas en vivo, las
    // suscripciones de Azure. Sin base, el filtro se arma solo con Azure.
    const subs = get<{ subscriptions: Subscription[] }>('/api/inventory/subscriptions')
      .then((r) => (r.subscriptions || []).filter((s) => s.subscriptionId))
      .catch(() => [] as Subscription[]);
    const nubes = get<CloudAccounts>('/api/accounts').catch(() => null);
    Promise.all([subs, nubes]).then(([lista, todas]) => {
      setSubscriptions(lista);
      const visibles = (todas?.configured ? todas.accounts : []).filter((a) => a.visible);
      const cuentas = visibles.length ? visibles : lista.map((s) => ({
        uid: `azure:sub/${s.subscriptionId.toLowerCase()}`, provider: 'azure', native_id: s.subscriptionId,
        name: s.displayName, visible: true,
      }));
      setAccounts(cuentas);
      if (todas?.providers.length) setLabels(Object.fromEntries(todas.providers.map((p) => [p.name, p.label])));
      setSelected(cuentas.map((a) => a.uid));
    }).finally(() => setLoaded(true));
  }, []);

  useEffect(() => {
    // El backend decide; esto solo evita ofrecer acciones que devolverían 403.
    get<Me>('/api/me').then(setMe).catch(() => setMe(null));
  }, []);

  const can = useCallback((role: Role) => Boolean(me?.permissions[role]), [me]);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', theme);
    try {
      localStorage.setItem('theme', theme);
    } catch {
      /* almacenamiento no disponible */
    }
  }, [theme]);

  const toast = useCallback((text: string) => {
    const id = ++toastId.current;
    setToasts((t) => [...t, { id, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3500);
  }, []);

  const askAgent = useCallback((agent: AgentType, question?: string) => {
    setDockAgent(agent);
    setDockOpen(true);
    if (question) setPending({ agent, text: question, id: Date.now() });
  }, []);

  const azure = useMemo(() => accounts.filter((a) => a.provider === 'azure'), [accounts]);
  const azureElegidas = useMemo(() => azure.filter((a) => selected.includes(a.uid)), [azure, selected]);
  const scope = useMemo(
    () => (azureElegidas.length === azure.length ? [] : azureElegidas.map((a) => a.native_id)),
    [azure, azureElegidas],
  );
  const scopeKey = scope.length ? [...scope].sort().join(',') : 'all';
  const azureNone = azure.length > 0 && azureElegidas.length === 0;
  const accountScope = useMemo(
    () => (selected.length === accounts.length ? [] : [...selected].sort()),
    [selected, accounts.length],
  );
  const accountKey = accountScope.length ? accountScope.join(',') : 'all';
  const inScope = useCallback(
    (uid: string | null | undefined) => !accountScope.length || (!!uid && accountScope.includes(uid)),
    [accountScope],
  );

  const value: AppState = {
    subscriptions, subscriptionsLoaded, accounts, providerLabels, selected, setSelected, scope, scopeKey,
    azureNone, accountScope, accountKey, inScope,
    theme, setTheme: setThemeState, toast, toasts,
    dockOpen, setDockOpen, dockAgent, setDockAgent, askAgent, pendingQuestion, me, can,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}


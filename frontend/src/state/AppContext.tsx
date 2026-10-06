import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Ctx, type AgentType, type AppState, type Theme, type Toast } from './context';
import { get } from '../lib/api';
import type { Subscription } from '../lib/types';

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
  const [selected, setSelected] = useState<string[]>([]);
  const [theme, setThemeState] = useState<Theme>(readTheme);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [dockOpen, setDockOpen] = useState(false);
  const [dockAgent, setDockAgent] = useState<AgentType>('inventory');
  const [pendingQuestion, setPending] = useState<AppState['pendingQuestion']>(null);
  const toastId = useRef(0);

  useEffect(() => {
    get<{ subscriptions: Subscription[] }>('/api/inventory/subscriptions')
      .then((r) => {
        const subs = (r.subscriptions || []).filter((s) => s.subscriptionId);
        setSubscriptions(subs);
        setSelected(subs.map((s) => s.subscriptionId));
      })
      .catch(() => setSubscriptions([]))
      .finally(() => setLoaded(true));
  }, []);

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

  const scope = useMemo(
    () => (selected.length === subscriptions.length ? [] : selected),
    [selected, subscriptions.length],
  );
  const scopeKey = scope.length ? [...scope].sort().join(',') : 'all';

  const value: AppState = {
    subscriptions, subscriptionsLoaded, selected, setSelected, scope, scopeKey,
    theme, setTheme: setThemeState, toast, toasts,
    dockOpen, setDockOpen, dockAgent, setDockAgent, askAgent, pendingQuestion,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}


import { useCallback, useContext, useEffect, useState } from 'react';
import { Ctx, type AppState } from './context';

export type { AgentType, Theme } from './context';

export function useApp(): AppState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useApp fuera de AppProvider');
  return ctx;
}

/** Ruta por hash: #/finops/costos -> ['finops', 'costos'] */
export function useRoute(): [string[], (path: string) => void] {
  const parse = () => window.location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  const [parts, setParts] = useState<string[]>(parse);
  useEffect(() => {
    const onHash = () => setParts(parse());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  const navigate = useCallback((path: string) => {
    window.location.hash = `/${path}`;
  }, []);
  return [parts, navigate];
}

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Carga datos del API con caché por clave.
 *
 * - Si hay un valor en caché se muestra de inmediato y se refresca detrás
 *   (`refreshing`), sin vaciar la pantalla ni saltos de layout.
 * - `reload()` fuerza una nueva petición.
 * - Una respuesta que llega tarde (la clave cambió mientras tanto) se descarta.
 */
const cache = new Map<string, unknown>();

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refreshing: boolean;
  reload: () => void;
}

export function useApi<T>(key: string | null, fetcher: () => Promise<T>): ApiState<T> {
  const [data, setData] = useState<T | null>(() => (key ? (cache.get(key) as T) ?? null : null));
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [nonce, setNonce] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    if (!key) return;
    let vigente = true;
    const cached = cache.get(key) as T | undefined;
    if (cached !== undefined) setData(cached);
    setPending(true);
    setError(null);
    fetcherRef
      .current()
      .then((value) => {
        if (!vigente) return;
        cache.set(key, value);
        setData(value);
      })
      .catch((e: unknown) => {
        if (!vigente) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (vigente) setPending(false);
      });
    return () => {
      vigente = false;
    };
  }, [key, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  return { data, error, loading: pending && data === null, refreshing: pending && data !== null, reload };
}

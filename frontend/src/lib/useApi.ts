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

/** Vacía la caché (pruebas: cada una empieza sin datos de la anterior). */
export function clearApiCache(): void {
  cache.clear();
}

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refreshing: boolean;
  reload: () => void;
}

export function useApi<T>(key: string | null, fetcher: () => Promise<T>): ApiState<T> {
  // Última respuesta recibida. `data` sobrevive al cambio de clave para no
  // vaciar la pantalla mientras llega la nueva.
  const [result, setResult] = useState<{ key: string; nonce: number; data: T | null; error: string | null } | null>(null);
  const [nonce, setNonce] = useState(0);
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    if (!key) return;
    let vigente = true;
    fetcherRef
      .current()
      .then((value) => {
        if (!vigente) return;
        cache.set(key, value);
        setResult({ key, nonce, data: value, error: null });
      })
      .catch((e: unknown) => {
        if (!vigente) return;
        setResult((prev) => ({ key, nonce, data: prev?.data ?? null, error: e instanceof Error ? e.message : String(e) }));
      });
    return () => {
      vigente = false;
    };
  }, [key, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  const current = key !== null && result?.key === key && result.nonce === nonce;
  const pending = key !== null && !current;
  const data = (key ? (cache.get(key) as T | undefined) : undefined) ?? result?.data ?? null;
  const error = current ? result.error : null;
  return { data, error, loading: pending && data === null, refreshing: pending && data !== null, reload };
}

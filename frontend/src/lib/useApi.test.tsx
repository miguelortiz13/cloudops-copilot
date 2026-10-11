import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useApi } from './useApi';

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

describe('useApi', () => {
  it('carga, y al volver a la misma clave muestra lo guardado mientras refresca', async () => {
    const fetcher = vi.fn().mockResolvedValue({ n: 1 });
    const first = renderHook(() => useApi('k1', fetcher));
    expect(first.result.current.loading).toBe(true);
    await waitFor(() => expect(first.result.current.data).toEqual({ n: 1 }));
    first.unmount();

    const lento = deferred<{ n: number }>();
    const second = renderHook(() => useApi('k1', () => lento.promise));
    // Sin vaciar la pantalla: dato anterior y "refrescando".
    expect(second.result.current.data).toEqual({ n: 1 });
    expect(second.result.current.loading).toBe(false);
    expect(second.result.current.refreshing).toBe(true);
    await act(async () => lento.resolve({ n: 2 }));
    expect(second.result.current.data).toEqual({ n: 2 });
    expect(second.result.current.refreshing).toBe(false);
  });

  it('descarta una respuesta que llega después de cambiar de clave', async () => {
    const a = deferred<string>();
    const b = deferred<string>();
    const { result, rerender } = renderHook(({ k }) => useApi(k, () => (k === 'a' ? a.promise : b.promise)), {
      initialProps: { k: 'a' },
    });
    rerender({ k: 'b' });
    await act(async () => b.resolve('dato de b'));
    await act(async () => a.resolve('dato tardío de a'));
    expect(result.current.data).toBe('dato de b');
  });

  it('un error conserva el dato anterior y reload vuelve a pedir', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce('ok').mockRejectedValueOnce(new Error('HTTP 503')).mockResolvedValueOnce('de nuevo');
    const { result } = renderHook(() => useApi('k2', fetcher));
    await waitFor(() => expect(result.current.data).toBe('ok'));

    act(() => result.current.reload());
    await waitFor(() => expect(result.current.error).toBe('HTTP 503'));
    expect(result.current.data).toBe('ok');

    act(() => result.current.reload());
    await waitFor(() => expect(result.current.data).toBe('de nuevo'));
    expect(result.current.error).toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it('sin clave no pide nada', () => {
    const fetcher = vi.fn();
    const { result } = renderHook(() => useApi(null, fetcher));
    expect(fetcher).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(false);
  });
});

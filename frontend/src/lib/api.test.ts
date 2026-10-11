import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetch = vi.fn();
vi.mock('../auth', () => ({ apiFetch: (...a: unknown[]) => apiFetch(...a) }));

const { ApiError, download, get, post, scopeQuery } = await import('./api');
const { API_URL } = await import('./config');

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('cliente del API', () => {
  beforeEach(() => apiFetch.mockReset());

  it('GET y POST pasan por apiFetch (que agrega el token) con la URL completa', async () => {
    apiFetch.mockImplementation(async () => json(200, { ok: true }));
    await expect(get('/api/me')).resolves.toEqual({ ok: true });
    expect(apiFetch).toHaveBeenLastCalledWith(`${API_URL}/api/me`, undefined);

    await post('/api/findings/1/status', { status: 'asumido' });
    const [, init] = apiFetch.mock.calls[apiFetch.mock.calls.length - 1];
    expect(init).toMatchObject({ method: 'POST', body: '{"status":"asumido"}' });
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' });
  });

  it('un error lleva el estado y el detalle que explica el backend', async () => {
    apiFetch.mockResolvedValue(json(403, { detail: 'Esta acción requiere el rol operador.' }));
    const error = (await get('/api/x').catch((e: unknown) => e)) as InstanceType<typeof ApiError>;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(403);
    expect(error.message).toBe('Esta acción requiere el rol operador.');
  });

  it('sin cuerpo JSON el mensaje es el código HTTP', async () => {
    apiFetch.mockResolvedValue(new Response('<html>Bad gateway</html>', { status: 502 }));
    await expect(get('/api/x')).rejects.toThrow('HTTP 502');
  });

  it('download: GET sin cuerpo, POST con cuerpo, y guarda el archivo con su nombre', async () => {
    const clicks: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push(this.download);
    });
    URL.createObjectURL = vi.fn(() => 'blob:x');
    URL.revokeObjectURL = vi.fn();
    apiFetch.mockImplementation(async () => new Response('a,b'));

    await download('/api/compliance/assets/export', undefined, 'activos.csv');
    expect(apiFetch).toHaveBeenLastCalledWith(`${API_URL}/api/compliance/assets/export`, undefined);
    await download('/api/inventory/export', { subscriptionIds: [] }, 'inventario.csv');
    expect(apiFetch.mock.calls[apiFetch.mock.calls.length - 1][1]).toMatchObject({ method: 'POST' });
    expect(clicks).toEqual(['activos.csv', 'inventario.csv']);

    apiFetch.mockResolvedValue(new Response('', { status: 500 }));
    await expect(download('/api/x', undefined, 'x.csv')).rejects.toThrow('HTTP 500');
  });

  it('scope: vacío significa todas las suscripciones', () => {
    expect(scopeQuery([])).toBe('');
    expect(scopeQuery(['a', 'b'])).toBe('?subscriptions=a%2Cb');
  });
});

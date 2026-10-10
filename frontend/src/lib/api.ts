/**
 * Cliente del API.
 *
 * Todas las llamadas pasan por `apiFetch` (adjunta el token de Entra ID) y por
 * una caché en memoria: volver a una pestaña muestra lo último que se cargó
 * mientras se refresca, en vez de vaciar la pantalla.
 */
import { apiFetch } from '../auth';
import { API_URL } from './config';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(`${API_URL}${path}`, init);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || body.message || detail;
    } catch {
      /* respuesta sin cuerpo JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/** Descarga con el token de la sesión: un enlace directo no lo llevaría. Sin `body`, la petición es GET. */
export async function download(path: string, body: unknown, filename: string): Promise<void> {
  const res = await apiFetch(`${API_URL}${path}`, body === undefined ? undefined : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Query string de scope para los endpoints GET. Vacío = todas las suscripciones. */
export function scopeQuery(subscriptionIds: string[]): string {
  return subscriptionIds.length ? `?subscriptions=${encodeURIComponent(subscriptionIds.join(','))}` : '';
}

export const downloadUrl = (filename: string) =>
  `${API_URL}/api/inventory/download/${encodeURIComponent(filename)}`;

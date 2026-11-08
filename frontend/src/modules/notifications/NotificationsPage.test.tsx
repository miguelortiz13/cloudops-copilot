import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearApiCache } from '../../lib/useApi';
import { renderWithApp } from '../../test/render';

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('../../lib/api', () => api);

const { NotificationsPage } = await import('./NotificationsPage');

const base = { dominio: 'activos', tipo: 'kubernetes', severidad: 'critica', clave: 'k', enlace: 'https://panel/#/activos/kubernetes/lab',
  canal: 'discord.com', modo: 'registro', silencio: null };

describe('Operación → Avisos', () => {
  beforeEach(() => {
    clearApiCache();
    api.get.mockResolvedValue({
      mode: 'registro', stats: { total: 3, enviados: 2, silenciados: 1, duplicados: 0, fallidos: 1 },
      items: [
        { ...base, at: '2026-11-08T03:00:00Z', titulo: 'Kubernetes · lab', decision: 'silenciado', enviado: true, error: null },
        { ...base, at: '2026-11-08T02:00:00Z', titulo: 'Incidente #31', tipo: 'incidente', dominio: 'operacion', decision: 'enviado', enviado: true, error: null },
        { ...base, at: '2026-11-08T01:30:00Z', titulo: 'Gasto anómalo', tipo: 'atencion_diaria', dominio: 'costos', modo: 'activo', decision: 'filtrado', enviado: false, error: null },
        { ...base, at: '2026-11-08T01:00:00Z', titulo: 'Resumen semanal', tipo: 'resumen_semanal', dominio: 'inicio', decision: 'enviado', enviado: false, error: 'El webhook (discord.com) respondio 500' },
      ],
    });
  });

  it('muestra qué decidió el motor y explica el modo registro', async () => {
    renderWithApp(<NotificationsPage />);
    expect(await screen.findByText(/modo registro/)).toBeInTheDocument();
    expect(screen.getByText('Enviado; en modo activo habría sido silenciado')).toBeInTheDocument();
    expect(screen.getByText('Falló: El webhook (discord.com) respondio 500')).toBeInTheDocument();
    expect(screen.getByText('Filtrado por severidad')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Kubernetes · lab' })).toHaveAttribute('href', '#/activos/kubernetes/lab');
    expect(api.get).toHaveBeenCalledWith('/api/notifications?dias=7');
  });
});

import { screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearApiCache } from '../../lib/useApi';
import { renderWithApp } from '../../test/render';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../../lib/api', () => api);

const { CostAlertsPage } = await import('./CostAlertsPage');

const alerta = { id: 4, kind: 'anomalia', provider: 'azure', account: 'sub-lab', day: '2026-11-07', amount: 3.2, reference: 0.4,
  title: 'Gasto anómalo en sub-lab el 07-11', status: 'abierto', assignee: null, note: null, explanation: null,
  opened_at: '2026-11-08T06:00:00Z', updated_by: null };

describe('Costos → Alertas', () => {
  beforeEach(() => {
    clearApiCache();
    api.get.mockResolvedValue({ open: 1, items: [alerta] });
    api.post.mockReset().mockImplementation(async (path: string) => (path.endsWith('/explicacion')
      ? { explanation: '**Por qué** subió Storage en stdatos' } : {}));
  });

  it('un operador explica la anomalía con IA y la resuelve con una nota', async () => {
    const { user } = renderWithApp(<CostAlertsPage />, { role: 'operador' });
    expect(await screen.findByText('$ 3,20 (media $ 0,40)')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: alerta.title }));
    await user.click(screen.getByRole('button', { name: /Explicar con IA/ }));
    expect(await screen.findByText(/subió Storage en stdatos/)).toBeInTheDocument();
    await user.type(screen.getByLabelText('Nota'), 'Carga de datos del equipo de BI');
    await user.click(screen.getByRole('button', { name: 'Resolver' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/costos/alertas/4', { status: 'resuelto', note: 'Carga de datos del equipo de BI' }));
  });

  it('un lector ve la alerta sin poder gestionarla', async () => {
    const { user } = renderWithApp(<CostAlertsPage />, { role: 'lector' });
    await user.click(await screen.findByRole('button', { name: alerta.title }));
    expect(screen.queryByRole('button', { name: 'Resolver' })).not.toBeInTheDocument();
  });
});

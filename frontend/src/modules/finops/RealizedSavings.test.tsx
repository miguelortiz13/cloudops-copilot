import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { renderWithApp } from '../../test/render';

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('../../lib/api', () => api);

const { RealizedSavings } = await import('./RealizedSavings');

describe('Ahorro realizado', () => {
  it('muestra lo verificado contra lo esperado y lo pendiente', async () => {
    api.get.mockResolvedValue({ days: 90, removed: [],
      applied: [
        { id: 1, name: 'disk-old', category: 'Disco sin VM', expected_monthly: 3.5, applied_by: 'ana', applied_at: '2026-11-01T10:00:00Z',
          status: 'verificado', removed_at: '2026-11-05T06:00:00Z', realized_monthly: 3.8 },
        { id: 2, name: 'pip-libre', category: 'IP pública libre', expected_monthly: 2.6, applied_by: 'ana', applied_at: '2026-11-07T10:00:00Z',
          status: 'pendiente', removed_at: null, realized_monthly: null },
      ],
      totals: { applied_pending: 1, expected_monthly: 6.1, realized_monthly: 3.8, removed_monthly: 3.8 } });
    renderWithApp(<RealizedSavings version={0} />);
    expect(await screen.findByText('Se esperaba $ 6,10')).toBeInTheDocument();
    expect(screen.getByText('Pendiente')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/costos/ahorro/realizado?dias=90');
  });
});

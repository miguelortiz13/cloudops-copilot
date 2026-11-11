import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearApiCache } from '../../lib/useApi';
import { renderWithApp } from '../../test/render';

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('../../lib/api', () => api);

const { SlosPage } = await import('./SlosPage');

describe('Operación → SLOs', () => {
  beforeEach(() => clearApiCache());

  it('muestra disponibilidad, presupuesto restante y la quema de cada servicio', async () => {
    api.get.mockResolvedValue({ objective_pct: 99.5, window_days: 28, items: [
      { url: 'https://tienda.example/salud', samples: 4032, failures: 9, availability_pct: 99.777, budget_consumed_pct: 44.6, budget_remaining_pct: 55.4, burn_1h: 0, burn_6h: 0.6, burning: false, met: true },
      { url: 'https://api.example/health', samples: 4032, failures: 31, availability_pct: 99.231, budget_consumed_pct: 153.8, budget_remaining_pct: -53.8, burn_1h: 33.3, burn_6h: 8.3, burning: true, met: false },
    ] });
    renderWithApp(<SlosPage />);
    expect(await screen.findByText('99,78 %')).toBeInTheDocument();
    expect(screen.getByText('En objetivo')).toBeInTheDocument();
    expect(screen.getByText('Quemando el presupuesto')).toBeInTheDocument();
    expect(screen.getByText('33,3×')).toBeInTheDocument();
    expect(screen.getByText(/el presupuesto de error es el 0,50 % de los chequeos/)).toBeInTheDocument();
  });
});

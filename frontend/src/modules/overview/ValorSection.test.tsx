import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearApiCache } from '../../lib/useApi';
import { renderWithApp } from '../../test/render';

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('../../lib/api', () => api);

const { ValorSection } = await import('./ValorSection');

const semana = (week: string, mtta: number | null, ruido: number | null, marcados: number | null) => ({
  week, start: '2026-11-02', findings: { detected: 1, resolved: 2, days_to_close: 4 },
  incidents: { total: 4, mtta_min: mtta, mttr_min: 23, noise_pct: ruido, marked_pct: marcados, correct_pct: 100 },
});

describe('Inicio · Valor de la operación', () => {
  beforeEach(() => clearApiCache());

  it('compara la última semana cerrada con la anterior y avisa si faltan marcas', async () => {
    api.get.mockResolvedValue({
      configured: true, findings_open: 6,
      weeks: [semana('2026-W44', 41, 44.4, 20), semana('2026-W45', 12, 25, 30), semana('2026-W46', 3, 0, 0)],
      savings: { realized_monthly: 2.52, expected_monthly: 3.1, applied_pending: 1 },
      evals: { at: '2026-11-09T07:10:00Z', on_target: 5, suites: [1, 2, 3, 4, 5].map((n) => ({ suite: `s${n}`, accuracy: 1, target: 0.9 })) },
    });
    renderWithApp(<ValorSection />);
    expect(await screen.findByText(/Semana 2026-W45 \(cerrada\)/)).toBeInTheDocument();  // la semana en curso no se compara
    expect(screen.getByText('12 min')).toBeInTheDocument();
    expect(screen.getByText('-29 min')).toBeInTheDocument();  // 12 contra 41
    expect(screen.getByText(/marcados 30 %: faltan marcas/)).toBeInTheDocument();
    expect(screen.getByText('5/5')).toBeInTheDocument();
    expect(screen.getByText(/6 abiertos hoy · 4,0 días para cerrar/)).toBeInTheDocument();
  });
});

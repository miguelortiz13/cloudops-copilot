import { describe, expect, it } from 'vitest';
import { monthlyUrl } from './monthly';

describe('reporte mensual por bloques', () => {
  it('todos los bloques no filtran; un subconjunto y la narración van en la URL', () => {
    expect(monthlyUrl('2026-10', ['costos', 'seguridad', 'inventario', 'incidentes', 'plataforma'], false)).toBe('/api/reports/monthly?month=2026-10');
    expect(monthlyUrl('2026-10', ['costos', 'incidentes'], true)).toBe('/api/reports/monthly?month=2026-10&bloques=costos%2Cincidentes&narrar=true');
  });
});

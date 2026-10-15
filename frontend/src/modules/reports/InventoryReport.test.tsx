import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { inventoryReport } from '../../test/fixtures';
import { renderWithApp } from '../../test/render';

const api = vi.hoisted(() => ({ get: vi.fn(), download: vi.fn() }));
vi.mock('../../lib/api', () => api);

const { InventoryReport } = await import('./InventoryReport');

describe('Inventario multinube', () => {
  beforeEach(() => {
    api.get.mockResolvedValue(inventoryReport());
    api.download.mockResolvedValue(undefined);
  });

  it('resume cada nube y cada cuenta', async () => {
    renderWithApp(<InventoryReport />);
    await screen.findByText('AWS laboratorio (demo)');
    expect(api.get).toHaveBeenCalledWith('/api/inventory/report');
    // Una tarjeta por nube (y la nube en cada fila de la tabla).
    expect(screen.getAllByText('Amazon Web Services')).toHaveLength(2);
    expect(screen.getAllByText('Microsoft Azure')).toHaveLength(3);
    // AWS sin costos conectados: desconocido, no cero.
    expect(screen.getByText('Costos aún no conectados: no es cero')).toBeInTheDocument();
    const fila = screen.getByText('AWS laboratorio (demo)').closest('tr')!;
    expect(within(fila).getByText('6')).toBeInTheDocument();
    expect(within(fila).getByTitle('Sin dato de costos para esta cuenta')).toHaveTextContent('—');
  });

  it('exporta el CSV con la sesión', async () => {
    renderWithApp(<InventoryReport />);
    (await screen.findByRole('button', { name: /Exportar CSV/ })).click();
    expect(api.download).toHaveBeenCalledWith('/api/inventory/report/export', undefined, 'inventario-multinube.csv');
  });

  it('sin recolección lo dice', async () => {
    api.get.mockResolvedValue({ ...inventoryReport(), providers: [], accounts: [] });
    renderWithApp(<InventoryReport />);
    expect(await screen.findByRole('status')).toHaveTextContent('todavía no registró recursos');
  });
});

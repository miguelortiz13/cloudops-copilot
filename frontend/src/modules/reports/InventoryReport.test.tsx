import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SUB_LAB, SUB_PROD, inventoryReport } from '../../test/fixtures';
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

  it('con el filtro recalcula la nube elegida a medias y exporta solo lo filtrado', async () => {
    const datos = inventoryReport();
    datos.resources = [
      { uid: 'r1', provider: 'azure', account_uid: `azure:sub/${SUB_PROD}`, account: 'Producción (demo)', name: 'kv', type: 'secrets.vault', region: 'eastus2', cost_30d: 3, in_iac: true },
      { uid: 'r2', provider: 'azure', account_uid: `azure:sub/${SUB_LAB}`, account: 'Laboratorio (demo)', name: 'st', type: 'storage.account', region: 'eastus2', cost_30d: null, in_iac: false },
    ];
    api.get.mockResolvedValue(datos);
    const solo = [`azure:sub/${SUB_PROD}`];
    const { user } = renderWithApp(<InventoryReport />, { state: { accountScope: solo, inScope: (u) => solo.includes(u ?? '') } });
    await screen.findByText('Producción (demo)');
    expect(screen.queryByText('Laboratorio (demo)')).not.toBeInTheDocument();
    expect(screen.queryByText('Amazon Web Services')).not.toBeInTheDocument();
    // La tarjeta de Azure cuenta solo la suscripción elegida.
    expect(screen.getByText('1 cuenta(s)')).toBeInTheDocument();
    expect(screen.getByText('secrets.vault')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Exportar CSV/ }));
    expect(api.download).toHaveBeenCalledWith(`/api/inventory/report/export?accounts=${encodeURIComponent(solo[0])}`, undefined, 'inventario-multinube.csv');
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

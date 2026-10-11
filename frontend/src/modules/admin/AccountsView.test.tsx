import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { connectedAccounts } from '../../test/fixtures';
import { renderWithApp } from '../../test/render';

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('../../lib/api', () => api);

const { AccountsView } = await import('./AccountsView');

function fila(nombre: string) {
  return screen.getByText(nombre).closest('tr')!;
}

describe('Cuentas conectadas', () => {
  beforeEach(() => api.get.mockResolvedValue(connectedAccounts()));

  it('muestra los permisos efectivos de cada cuenta', async () => {
    renderWithApp(<AccountsView />);
    await screen.findByText('Producción (demo)');
    expect(api.get).toHaveBeenCalledWith('/api/admin/accounts');
    expect(within(fila('Producción (demo)')).getByText('Con permiso')).toBeInTheDocument();
    // Sin permiso de costos: el gasto es desconocido (raya), no cero.
    const lab = fila('Laboratorio (demo)');
    expect(within(lab).getByText('Sin permiso')).toBeInTheDocument();
    expect(within(lab).getByTitle('Sin dato de costos para esta cuenta')).toHaveTextContent('—');
    expect(within(fila('Retirada (demo)')).getByText('No visible')).toBeInTheDocument();
  });

  it('explica qué falta y cómo resolverlo', async () => {
    renderWithApp(<AccountsView />);
    await screen.findByText('Producción (demo)');
    const avisos = screen.getAllByRole('alert').map((a) => a.textContent);
    expect(avisos.some((t) => t?.includes('Una cuenta dejó de aparecer'))).toBe(true);
    expect(avisos.some((t) => t?.includes('falta el rol Cost Management Reader'))).toBe(true);
  });

  it('declara las capacidades, incluidas las que no están configuradas', async () => {
    renderWithApp(<AccountsView />);
    await screen.findByText('Producción (demo)');
    expect(screen.getByText('Estados de Terraform').closest('div')!.parentElement).toHaveTextContent('No configurada');
    expect(screen.getByText(/TFSTATE_ACCOUNT/)).toBeInTheDocument();
    expect(screen.getAllByText('Activa')).toHaveLength(4);
    expect(screen.getByText('00000000-0000-4000-8000-0000000000c1')).toBeInTheDocument();
  });

  it('sin base de datos lo dice', async () => {
    api.get.mockResolvedValue({ configured: false, providers: [], accounts: [] });
    renderWithApp(<AccountsView />);
    expect(await screen.findByRole('status')).toHaveTextContent('Sin base de datos');
  });
});

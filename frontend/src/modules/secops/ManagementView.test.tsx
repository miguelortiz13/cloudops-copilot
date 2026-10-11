import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { findingEvents, managedFindings } from '../../test/fixtures';
import { renderWithApp } from '../../test/render';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../../lib/api', () => api);

const { ManagementView } = await import('./ManagementView');

function gestionar(nombre: string) {
  return within(screen.getByText(nombre, { exact: false, selector: '.sub' }).closest('tr')!).getByRole('button');
}

describe('Gestión de hallazgos', () => {
  beforeEach(() => {
    api.get.mockImplementation(async (path: string) => (path === '/api/findings' ? managedFindings() : findingEvents));
    api.post.mockReset();
  });

  it('muestra los activos por defecto y filtra por estado', async () => {
    const { user } = renderWithApp(<ManagementView />);
    expect(await screen.findByText('Puerto de administración abierto a internet')).toBeInTheDocument();
    expect(screen.getAllByRole('row')).toHaveLength(3);
    await user.click(screen.getByRole('radio', { name: 'Aceptados (1)' }));
    expect(screen.getByText('hasta el 31 de dic de 2026', { normalizer: (s) => s.replace(/\s+/g, ' ') })).toBeInTheDocument();
  });

  it('aceptar un riesgo exige fecha de vencimiento y justificación', async () => {
    api.post.mockResolvedValue({ ...managedFindings().items[1], status: 'aceptado', accepted_until: '2027-01-31' });
    const { user, app } = renderWithApp(<ManagementView />, { role: 'operador' });
    await screen.findByText('kv-pagos-prod', { exact: false });
    await user.click(gestionar('kv-pagos-prod'));
    const panel = screen.getByRole('dialog', { name: 'Key Vault alcanzable desde red pública' });
    // Los controles que incumple el hallazgo.
    expect(within(panel).getByText('CIS 8.7')).toBeInTheDocument();
    await user.click(within(panel).getByRole('button', { name: 'Aceptar el riesgo' }));

    const confirmar = within(panel).getByRole('button', { name: 'Aceptar el riesgo' });
    expect(confirmar).toBeDisabled();
    await user.type(within(panel).getByLabelText(/^Justificación/), 'Mitigado por firewall de aplicación');
    expect(confirmar).toBeDisabled();
    await user.type(within(panel).getByLabelText(/^Vence el/), '2027-01-31');
    await user.click(confirmar);

    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/findings/2/status', {
      status: 'aceptado', note: 'Mitigado por firewall de aplicación', owner: undefined, accepted_until: '2027-01-31',
    }));
    expect(app.toast).toHaveBeenCalledWith('Estado actualizado: Riesgo aceptado.');
  });

  it('un lector no ve acciones de gestión', async () => {
    const { user } = renderWithApp(<ManagementView />, { role: 'lector' });
    await screen.findByText('kv-pagos-prod', { exact: false });
    await user.click(gestionar('kv-pagos-prod'));
    const panel = screen.getByRole('dialog');
    expect(within(panel).queryByRole('button', { name: 'Asumir' })).not.toBeInTheDocument();
    expect(within(panel).getByText(/requiere el rol Operador/)).toBeInTheDocument();
    expect(await within(panel).findByText('Detectado por el recolector')).toBeInTheDocument();
  });

  it('un hallazgo resuelto no se gestiona a mano', async () => {
    const { user } = renderWithApp(<ManagementView />, { role: 'administrador' });
    await screen.findByText('kv-pagos-prod', { exact: false });
    await user.click(screen.getByRole('radio', { name: 'Resueltos (1)' }));
    await user.click(screen.getByRole('button', { name: 'Ver' }));
    const panel = screen.getByRole('dialog');
    expect(within(panel).getByText(/Se resolvió solo/)).toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: /Asumir|Aceptar|Reabrir/ })).not.toBeInTheDocument();
  });
});

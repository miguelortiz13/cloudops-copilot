import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { complianceStatus, classifiedAssets } from '../../test/fixtures';
import { renderWithApp } from '../../test/render';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), download: vi.fn() }));
vi.mock('../../lib/api', () => api);

const { CompliancePage } = await import('./CompliancePage');
const { ControlRefs } = await import('./controls');

function codigos() {
  return screen.getAllByRole('row').slice(1).map((r) => r.querySelector('td')?.textContent);
}

describe('Cumplimiento', () => {
  beforeEach(() => {
    api.get.mockImplementation(async (path: string) => (path === '/api/compliance' ? complianceStatus() : classifiedAssets()));
  });

  it('muestra los controles del marco con su estado y avisa de las reglas sin evaluar', async () => {
    renderWithApp(<CompliancePage view={undefined} onView={vi.fn()} onGo={vi.fn()} />);
    expect(await screen.findByText('6.2')).toBeInTheDocument();
    expect(codigos()).toEqual(['3.7', '6.2', '8.7', '9.2']);
    expect(screen.getByRole('alert')).toHaveTextContent('Una regla no se pudo evaluar');
    // Cobertura honesta: cuántos controles se evalúan, no un porcentaje del marco.
    expect(screen.getByText(/evalúa 4 controles de este marco/)).toBeInTheDocument();
    const fila = screen.getByText('9.2').closest('tr')!;
    expect(within(fila).getByText('Sin evidencia')).toBeInTheDocument();
  });

  it('cambia de marco y filtra por estado', async () => {
    const { user } = renderWithApp(<CompliancePage view="controles" onView={vi.fn()} onGo={vi.fn()} />);
    await screen.findByText('6.2');
    await user.click(screen.getByRole('radio', { name: 'No cumple (2)' }));
    expect(codigos()).toEqual(['6.2', '8.7']);

    await user.click(screen.getByRole('radio', { name: 'ISO 27001:2022' }));
    // El filtro vuelve a "Todos" al cambiar de marco.
    expect(codigos()).toEqual(['A.5.9', 'A.5.12', 'A.8.20']);
    const a59 = screen.getByText('A.5.9').closest('tr')!;
    expect(within(a59).getByText('Clasificación de activos')).toBeInTheDocument();
    expect(within(a59).getByText('solo parcial')).toBeInTheDocument();
  });

  it('el detalle de un control lleva a sus hallazgos', async () => {
    const onGo = vi.fn();
    const { user } = renderWithApp(<CompliancePage view="controles" onView={vi.fn()} onGo={onGo} />);
    await screen.findByText('8.7');
    await user.click(within(screen.getByText('8.7').closest('tr')!).getByRole('button', { name: 'Detalle' }));
    const panel = screen.getByRole('dialog', { name: 'CIS 8.7' });
    expect(within(panel).getByText('Key Vault alcanzable desde red pública')).toBeInTheDocument();
    expect(within(panel).getByText(/Añadir private endpoint/)).toBeInTheDocument();
    await user.click(within(panel).getByRole('button', { name: 'Ir a la gestión de hallazgos' }));
    expect(onGo).toHaveBeenCalledWith('secops/gestion');
  });

  it('el catálogo muestra el mapeo y marca la evidencia parcial', async () => {
    const { user } = renderWithApp(<CompliancePage view="reglas" onView={vi.fn()} onGo={vi.fn()} />);
    await screen.findByText('network.admin-port-open');
    const fila = screen.getByText('network.admin-port-open').closest('tr')!;
    expect(within(fila).getByText('ISO A.8.22*')).toHaveAttribute('title', 'Evidencia parcial');
    await user.click(within(fila).getByRole('button', { name: 'Detalle' }));
    const panel = screen.getByRole('dialog');
    expect(within(panel).getByText('Reglas Allow con origen * hacia 22 o 3389.')).toBeInTheDocument();
    expect(within(panel).getByRole('link', { name: /learn.microsoft.com/ })).toHaveAttribute('target', '_blank');
  });

  it('las pestañas navegan por la URL', async () => {
    const onView = vi.fn();
    const { user } = renderWithApp(<CompliancePage view="controles" onView={onView} onGo={vi.fn()} />);
    await user.click(screen.getByRole('tab', { name: 'Clasificación de activos' }));
    expect(onView).toHaveBeenCalledWith('activos');
  });

  it('ControlRefs: sin controles muestra una raya', () => {
    const { container, rerender } = renderWithApp(<ControlRefs frameworks={{}} />);
    expect(container).toHaveTextContent('—');
    rerender(<ControlRefs frameworks={{ 'cis-azure-2.0.0': [{ control: '4.1.2', match: 'parcial' }] }} />);
    expect(container).toHaveTextContent('CIS 4.1.2*');
  });
});

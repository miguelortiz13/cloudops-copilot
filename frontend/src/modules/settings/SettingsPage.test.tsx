import { screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearApiCache } from '../../lib/useApi';
import { renderWithApp } from '../../test/render';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }));
vi.mock('../../lib/api', () => api);

const { SettingsPage } = await import('./SettingsPage');

const secciones = {
  incidentes: { values: {}, defaults: {}, origin: 'defecto', schema: {} },
  gobierno: { values: { tags_obligatorias: ['Environment', 'Project'], tags_showback: ['Project'] }, defaults: {}, origin: 'variable',
    schema: { tags_obligatorias: ['nombres', 20, false], tags_showback: ['nombres', 10, false] } },
  costos: { values: { presupuesto_azure_usd: 5, presupuesto_aws_usd: 5 }, defaults: {}, origin: 'ajuste',
    schema: { presupuesto_azure_usd: ['float', 0, 1e6], presupuesto_aws_usd: ['float', 0, 1e6] } },
  ia: { values: { max_consultas_hora: 30, max_consultas_dia: 150 }, defaults: {}, origin: 'variable',
    schema: { max_consultas_hora: ['int', 0, 10000], max_consultas_dia: ['int', 0, 100000] } },
};
const historial = [{ at: '2026-11-08T03:00:00Z', actor: 'ana@contoso.example', seccion: 'costos',
  antes: { presupuesto_azure_usd: 5 }, despues: { presupuesto_azure_usd: 8 } }];

describe('Plataforma → Ajustes', () => {
  beforeEach(() => {
    clearApiCache();
    api.get.mockImplementation(async (path: string) => {
      if (path === '/api/settings') return { sections: secciones };
      if (path === '/api/settings-history') return { items: historial };
      return { values: { ventana_tormenta_seg: 120, umbral_tormenta: 3, foto_vieja_min: 15, diagnosticar: ['critica'],
        avisar: ['critica'], postmortem: true, max_diagnosticos_hora: 0 }, limits: {} };
    });
    api.put.mockReset().mockResolvedValue({});
    api.post.mockReset().mockResolvedValue({});
  });

  it('un administrador cambia las tags obligatorias y deshace un cambio', async () => {
    const { user } = renderWithApp(<SettingsPage onGo={vi.fn()} />);
    const tags = await screen.findByLabelText(/^Tags obligatorias/);
    expect(tags).toHaveValue('Environment, Project');
    await user.clear(tags);
    await user.type(tags, 'Environment, Owner ,');
    await user.click(screen.getAllByRole('button', { name: 'Guardar' })[1]);
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/api/settings/gobierno', {
      tags_obligatorias: ['Environment', 'Owner'], tags_showback: ['Project'] }));

    expect(screen.getByText('presupuesto_azure_usd: 5 → 8')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Deshacer' }));
    expect(api.post).toHaveBeenCalledWith('/api/settings-history/0/undo', {});
  });

  it('un lector ve los ajustes sin poder cambiarlos', async () => {
    renderWithApp(<SettingsPage onGo={vi.fn()} />, { role: 'lector' });
    expect(await screen.findByLabelText(/^Presupuesto de Azure/)).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Deshacer' })).not.toBeInTheDocument();
  });
});

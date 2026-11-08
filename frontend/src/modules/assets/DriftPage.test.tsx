import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearApiCache } from '../../lib/useApi';
import { renderWithApp } from '../../test/render';

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('../../lib/api', () => api);

const { DriftPage } = await import('./DriftPage');

describe('Activos → Drift de Terraform', () => {
  beforeEach(() => clearApiCache());

  it('muestra lo borrado fuera de Terraform y las tags cambiadas, y lleva a la ficha', async () => {
    api.get.mockResolvedValue({ available: true, generated_at: '2026-11-08T06:00:00Z', states_read: 2, totals: { deleted: 1, tags: 1 },
      deleted: [{ id: '/subscriptions/1/x/kv-viejo', name: 'kv-viejo', terraform_type: 'azurerm_key_vault' }],
      tags: [{ uid: 'azure:/x/stdatos', name: 'stdatos', type: 'storage.account', changes: [{ tag: 'Owner', terraform: 'plataforma', real: null }] }] });
    const onRecurso = vi.fn();
    const { user } = renderWithApp(<DriftPage onRecurso={onRecurso} />);
    expect(await screen.findByText('kv-viejo')).toBeInTheDocument();
    expect(screen.getByText('no la tiene')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'stdatos' }));
    expect(onRecurso).toHaveBeenCalledWith('azure:/x/stdatos');
  });

  it('sin cálculo todavía lo explica', async () => {
    api.get.mockResolvedValue({ available: false, deleted: [], tags: [], totals: { deleted: 0, tags: 0 } });
    renderWithApp(<DriftPage onRecurso={vi.fn()} />);
    expect(await screen.findByText('Todavía sin cálculo')).toBeInTheDocument();
  });
});

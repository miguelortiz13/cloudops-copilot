import { screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearApiCache } from '../../lib/useApi';
import { renderWithApp } from '../../test/render';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../../lib/api', () => api);

const { ResourcesPage } = await import('./ResourcesPage');

const UID = 'azure:/subscriptions/1/resourcegroups/rg/providers/microsoft.storage/storageaccounts/stdatos';
const ficha = {
  uid: UID, name: 'stdatos', provider: 'azure', type: 'storage.account', native_type: 'x', region: 'eastus2', group: 'rg',
  account: { uid: 'azure:sub/1', name: 'lab' }, tags: { environment: 'dev' }, missing_tags: ['Project'], in_iac: false,
  created_by: 'ana@contoso.example', first_seen: '2026-10-01T00:00:00Z', last_seen: '2026-11-07T00:00:00Z', deleted_at: null,
  cost: { total_30d: 5, currency: 'USD', daily: [], by_service: [{ service: 'Storage', cost: 5 }] },
  findings: [{ id: 1, title: 'Blobs públicos', severity: 'alta', status: 'abierto', owner: null, accepted_until: null, remediation: 'Desactivar' }],
  open_findings: 1, classification: { classification: 'Confidencial', confidentiality: 3, integrity: 2, availability: 1, custodian: null },
  cluster: null, incidents: [], timeline: [{ at: '2026-10-01T00:00:00Z', kind: 'recurso.visto', actor: 'ana@contoso.example', text: 'Apareció en el inventario' }],
};

describe('Activos → Recursos', () => {
  beforeEach(() => {
    clearApiCache();
    api.get.mockImplementation(async (path: string) => path.startsWith('/api/activos/ficha') ? ficha : {
      total: 1, providers: ['aws', 'azure'],
      items: [{ uid: UID, provider: 'azure', account_uid: 'azure:sub/1', account: 'lab', name: 'stdatos', type: 'storage.account',
        region: 'eastus2', cost_30d: 5, currency: 'USD', in_iac: false, classification: 'Confidencial' }],
    });
    api.post.mockReset().mockResolvedValue({ explanation: '**Qué es** una cuenta de almacenamiento' });
  });

  it('lista multinube y lleva a la ficha', async () => {
    const onRecurso = vi.fn();
    const { user } = renderWithApp(<ResourcesPage onRecurso={onRecurso} onGo={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: 'stdatos' }));
    expect(onRecurso).toHaveBeenCalledWith(UID);
    await user.click(screen.getByRole('radio', { name: 'AWS' }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/api/activos/recursos?q=&nube=aws&pagina=1&por_pagina=50'));
  });

  it('la ficha junta gasto, hallazgos y gobierno, y la IA la explica', async () => {
    const { user } = renderWithApp(<ResourcesPage uid={encodeURIComponent(UID)} onRecurso={vi.fn()} onGo={vi.fn()} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'stdatos' })).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith(`/api/activos/ficha?uid=${encodeURIComponent(UID)}`);
    expect(screen.getByText('Blobs públicos')).toBeInTheDocument();
    expect(screen.getByText('Faltan las tags obligatorias: Project.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Explicar con IA/ }));
    expect(await screen.findByText(/una cuenta de almacenamiento/)).toBeInTheDocument();
    expect(api.post).toHaveBeenCalledWith('/api/activos/ficha/explicacion', { uid: UID });
  });
});

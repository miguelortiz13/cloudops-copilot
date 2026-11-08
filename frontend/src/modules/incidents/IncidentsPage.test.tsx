import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { IncidentDetail, IncidentSummary } from '../../lib/types';
import { clearApiCache } from '../../lib/useApi';
import { renderWithApp } from '../../test/render';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }));
vi.mock('../../lib/api', () => api);

const { IncidentsPage } = await import('./IncidentsPage');
const { IncidentSettingsView } = await import('./IncidentSettingsView');
const { SilencesPage } = await import('./SilencesView');

const resumen: IncidentSummary = {
  id: 7, title: 'Tormenta en lab: 3 incidentes · PodCrashLooping · boutique · svc0-1', severity: 'alta', status: 'abierto',
  cluster: 'lab', source: 'alertmanager', opened_at: '2026-11-05T04:07:00Z', resolved_at: null, diagnosis_status: 'listo',
  feedback: null, alerts: 1, assignee: null, closed_reason: null, parent_id: null,
};
const detalle: IncidentDetail = {
  ...resumen, diagnosis: '**Causa probable** (confianza alta): se reinició la máquina.', tools: [], diagnosed_at: '2026-11-05T04:08:00Z',
  last_alert_at: '2026-11-05T04:07:00Z', postmortem: null,
  children: [{ ...resumen, id: 8, parent_id: 7, title: 'PodCrashLooping · boutique · svc1-1' }],
  events: [{ at: '2026-11-05T04:07:00Z', actor: 'alertmanager', kind: 'abierto', text: '1 alerta(s)' }],
  alert_list: [{ name: 'PodCrashLooping', status: 'firing', severity: 'alta', labels: { namespace: 'boutique', pod: 'svc0-1' },
    summary: 'Pod svc0-1 en CrashLoopBackOff', description: '', starts_at: '' }],
};
const stats = { configured: true, days: 30, total: 4, open: 1, diagnosed: 3, marked: 2, correct: 1, accuracy: 0.5, target: 0.9, noise: 1, median_minutes_to_resolve: 12 };

describe('Incidentes', () => {
  beforeEach(() => {
    clearApiCache();
    api.get.mockImplementation(async (path: string) => {
      if (path.startsWith('/api/incidents?')) return { configured: true, items: [resumen] };
      if (path === '/api/incidents/stats') return stats;
      if (path === '/api/silences') return { items: [] };
      if (path === '/api/settings/incidents') return { values: { ventana_tormenta_seg: 120, umbral_tormenta: 3, foto_vieja_min: 15,
        diagnosticar: ['critica', 'alta', 'media'], avisar: ['critica', 'alta', 'media'], postmortem: true, max_diagnosticos_hora: 0 }, limits: {} };
      return detalle;
    });
    api.post.mockReset().mockResolvedValue({});
    api.put.mockReset().mockResolvedValue({});
  });

  it('muestra la precisión, filtra por estado y explica la tormenta', async () => {
    const { user } = renderWithApp(<IncidentsPage onIncidente={vi.fn()} />);
    expect(await screen.findByText('1 de 2 marcados · objetivo 90 %')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/incidents?dias=30&estado=vivos');
    expect(await screen.findByText(/Tormenta: 1 incidente\(s\) más/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Severidad'), 'critica');
    expect(api.get).toHaveBeenCalledWith('/api/incidents?dias=30&estado=vivos&severidad=critica');
  });

  it('un operador reconoce, cierra con motivo, anota y silencia', async () => {
    const { user } = renderWithApp(<IncidentsPage onIncidente={vi.fn()} />, { role: 'operador' });
    await user.click(await screen.findByRole('button', { name: 'Reconocer' }));
    expect(api.post).toHaveBeenCalledWith('/api/incidents/7/status', { status: 'reconocido' });

    await user.click(screen.getByRole('button', { name: 'Cerrar…' }));
    await user.selectOptions(screen.getByLabelText(/^Motivo/), 'ruido');
    await user.click(screen.getByRole('button', { name: 'Cerrar incidente' }));
    expect(api.post).toHaveBeenCalledWith('/api/incidents/7/status', { status: 'cerrado', reason: 'ruido', comment: '' });

    await user.type(screen.getByLabelText('Nota'), 'Reinicié WSL');
    await user.click(screen.getByRole('button', { name: 'Agregar' }));
    expect(api.post).toHaveBeenCalledWith('/api/incidents/7/notes', { text: 'Reinicié WSL' });

    await user.click(screen.getByRole('button', { name: 'Silenciar similares…' }));
    await user.click(screen.getByRole('button', { name: 'Silenciar' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/silences', {
      hours: 24, reason: '', cluster: 'lab', namespace: 'boutique', alertname: 'PodCrashLooping', target: null }));
  });

  it('un lector no ve acciones', async () => {
    renderWithApp(<IncidentsPage onIncidente={vi.fn()} />, { role: 'lector' });
    await screen.findByText(/se reinició la máquina/);
    expect(screen.queryByRole('button', { name: 'Reconocer' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Nota')).not.toBeInTheDocument();
  });

  it('un administrador cambia los ajustes y no se puede silenciar todo', async () => {
    const { user } = renderWithApp(<IncidentSettingsView />);
    const ventana = await screen.findByLabelText(/^Ventana de tormenta/);
    await user.clear(ventana);
    await user.type(ventana, '300');
    await user.click(screen.getAllByRole('checkbox', { name: /Media/ })[1]);  // no avisar las medias
    await user.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(api.put).toHaveBeenCalledWith('/api/settings/incidents', expect.objectContaining({ ventana_tormenta_seg: 300, avisar: ['critica', 'alta'] }));

    renderWithApp(<SilencesPage />);
    await user.click(await screen.findByRole('button', { name: 'Nuevo silencio' }));
    const form = screen.getByRole('button', { name: 'Silenciar' });
    expect(form).toBeDisabled();
    expect(within(form.closest('.stack')!).getByText(/no se puede silenciar todo/)).toBeInTheDocument();
  });
});

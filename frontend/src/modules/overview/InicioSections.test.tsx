import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearApiCache } from '../../lib/useApi';
import { renderWithApp } from '../../test/render';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../../lib/api', () => api);

const { MisPendientes, QueCambio } = await import('./InicioSections');
const { Sidebar } = await import('../../components/layout');

const pendiente = (n: number, urgency = 1) => ({ type: 'incidente', title: `#${n} Alerta`, why: 'Asignado a ti · abierto', urgency, link: `#/operacion/incidentes/${n}`, when: null });

describe('Inicio', () => {
  beforeEach(() => { clearApiCache(); localStorage.clear(); });

  it('Mis pendientes muestra el porqué, enlaza cada uno y despliega los que sobran', async () => {
    api.get.mockResolvedValue({ configured: true, items: [pendiente(1, 3), ...[2, 3, 4, 5, 6, 7, 8].map((n) => pendiente(n))] });
    const { user } = renderWithApp(<MisPendientes />);
    expect(await screen.findByRole('link', { name: '#1 Alerta' })).toHaveAttribute('href', '#/operacion/incidentes/1');
    expect(screen.getAllByText('Asignado a ti · abierto')).toHaveLength(6);
    await user.click(screen.getByRole('button', { name: 'Ver los 8' }));
    expect(screen.getAllByText('Asignado a ti · abierto')).toHaveLength(8);
  });

  it('la IA propone por dónde empezar, con enlaces a cada pendiente', async () => {
    api.get.mockResolvedValue({ configured: true, items: [pendiente(40, 3), pendiente(26, 3)] });
    api.post.mockResolvedValue({ text: '**Por dónde empezar:**\n- Reconoce [#40](#/operacion/incidentes/40): imagen inexistente.' });
    const { user } = renderWithApp(<MisPendientes />);
    await user.click(await screen.findByRole('button', { name: 'Por dónde empiezo' }));
    expect(api.post).toHaveBeenCalledWith('/api/inicio/pendientes/priorizar', {});
    expect(await screen.findByRole('link', { name: '#40' })).toHaveAttribute('href', '#/operacion/incidentes/40');
  });

  it('Qué cambió usa la última visita y solo lista lo que cambió', async () => {
    localStorage.setItem('cloudops.ultimaVisita', '2026-11-08T10:00:00.000Z');
    api.get.mockResolvedValue({ configured: true, since: '2026-11-08T10:00:00+00:00',
      incidents: { new: 2, resolved: 0, latest: [{ id: 9, title: 'PodCrashLooping', severity: 'alta', status: 'abierto' }] },
      findings: { new: 0, new_critical: 0, resolved: 3 }, resources: { new: 0, new_outside_iac: 0, deleted: 0 }, cost_alerts: { new: 0 } });
    renderWithApp(<QueCambio />);
    expect(await screen.findByRole('link', { name: '2 incidentes nuevos' })).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith(`/api/inicio/cambios?desde=${encodeURIComponent('2026-11-08T10:00:00.000Z')}`);
    expect(screen.getByRole('link', { name: '3 hallazgos resueltos' })).toBeInTheDocument();
    expect(screen.queryByText(/recurso/)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '#9 PodCrashLooping' })).toBeInTheDocument();
  });
});

describe('Barra lateral', () => {
  beforeEach(() => localStorage.clear());

  it('pliega un grupo, lo recuerda y nunca oculta la sección abierta', async () => {
    const { user } = renderWithApp(<Sidebar active="costos/gasto" mobileOpen={false} onNavigate={() => {}} />);
    const nav = screen.getByRole('navigation', { name: 'Secciones' });
    await user.click(within(nav).getByRole('button', { name: 'Riesgo' }));
    expect(within(nav).queryByRole('link', { name: 'Hallazgos' })).not.toBeInTheDocument();
    expect(within(nav).getByRole('button', { name: 'Riesgo' })).toHaveAttribute('aria-expanded', 'false');
    expect(JSON.parse(localStorage.getItem('cloudops.navPlegados') || '[]')).toEqual(['riesgo']);
    await user.click(within(nav).getByRole('button', { name: 'Costos' }));
    expect(within(nav).getByRole('link', { name: 'Gasto' })).toBeInTheDocument();  // es la sección abierta
  });
});

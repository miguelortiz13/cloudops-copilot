import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearApiCache } from '../../lib/useApi';
import { renderWithApp } from '../../test/render';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../../lib/api', () => api);

const { ConocimientoSection } = await import('./ConocimientoSection');

describe('Plataforma → IA · Base de conocimiento', () => {
  beforeEach(() => clearApiCache());

  it('muestra lo indexado, reindexa y prueba la búsqueda con sus fuentes', async () => {
    api.get.mockImplementation(async (path: string) => (path.startsWith('/api/ia/conocimiento/buscar')
      ? { modo: 'híbrido', resultados: [
        { tipo: 'incidente', titulo: 'Incidente #900: KubePodCrashLooping', fuente: 'incidente/900', enlace: '#/operacion/incidentes/900', texto: 'redis-cart sin endpoints' },
        { tipo: 'runbook', titulo: 'Runbook: pod en CrashLoopBackOff · Diagnóstico', fuente: 'conocimiento/runbooks/k8s-crashloopbackoff.md#2', enlace: null, texto: 'kubectl logs --previous' }] }
      : { indexado: true, modelo: 'gemini-embedding-001', actualizado: '2026-11-09T06:20:00Z', fragmentos: 81, con_vector: 81, por_tipo: { runbook: 40, incidente: 8 } }));
    api.post.mockResolvedValue({ started: true });
    const { user } = renderWithApp(<ConocimientoSection />);
    expect(await screen.findByText(/81 fragmentos \(Runbooks: 40 · Incidentes resueltos: 8\)/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Reindexar' }));
    expect(api.post).toHaveBeenCalledWith('/api/ia/conocimiento/reindexar', {});
    await user.type(screen.getByLabelText('Probar la búsqueda'), 'connection refused redis');
    await user.click(screen.getByRole('button', { name: 'Buscar' }));
    expect(await screen.findByRole('link', { name: 'Incidente #900: KubePodCrashLooping' })).toHaveAttribute('href', '#/operacion/incidentes/900');
    expect(screen.getByText('conocimiento/runbooks/k8s-crashloopbackoff.md#2')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/ia/conocimiento/buscar?q=connection%20refused%20redis');
  });
});

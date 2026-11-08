import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearApiCache } from '../../lib/useApi';
import { renderWithApp } from '../../test/render';

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('../../lib/api', () => api);

const { AiPage } = await import('./AiPage');

const bloque = { calls: 4, errors: 1, input_tokens: 32000, output_tokens: 1800, cost_usd: 0.0196, p50_ms: 8200, p95_ms: 9800 };

describe('Plataforma → IA', () => {
  beforeEach(() => clearApiCache());

  it('muestra costo, latencia por dominio y abre una traza con sus pasos', async () => {
    api.get.mockImplementation(async (path: string) => {
      if (path.startsWith('/api/ia/resumen')) return { days: 7, priced: true, total: bloque, by_domain: { operacion: bloque }, by_use: { 'incidente.diagnostico': bloque }, tools: [{ name: 'estado_cluster', calls: 3, errors: 0 }] };
      if (path.startsWith('/api/ia/trazas?')) return { total: 1, items: [{ trace_id: 'a1b2', name: 'invoke_agent incidente.diagnostico', start: '2026-11-09T06:00:00Z', duration_ms: 8200, spans: 2,
        attributes: { 'cloudops.use': 'incidente.diagnostico', 'gen_ai.usage.input_tokens': 8000, 'gen_ai.usage.output_tokens': 400 } }] };
      return { trace_id: 'a1b2', name: 'invoke_agent incidente.diagnostico', start: '2026-11-09T06:00:00Z', duration_ms: 8200,
        attributes: { 'gen_ai.request.model': 'gemini-3.5-flash' },
        spans: [{ name: 'chat gemini-3.5-flash', duration_ms: 2000, attributes: { 'gen_ai.operation.name': 'chat', 'gen_ai.usage.input_tokens': 4000, 'gen_ai.usage.output_tokens': 50, 'cloudops.tool_calls': 1 } },
          { name: 'execute_tool estado_cluster', duration_ms: 300, attributes: { 'gen_ai.operation.name': 'execute_tool', 'cloudops.tool.arguments': { nombre: 'lab' }, 'cloudops.tool.result_chars': 5200 } }] };
    });
    const { user } = renderWithApp(<IaWrapper />);
    expect(await screen.findByText('Operación')).toBeInTheDocument();
    expect(screen.getAllByText('9,8 s').length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: /9\/11\/2026|11\/9\/2026|2026/ }));
    expect(await screen.findByText('execute_tool estado_cluster')).toBeInTheDocument();
  });

  it('sin precio configurado no inventa el costo', async () => {
    api.get.mockImplementation(async (path: string) => (path.startsWith('/api/ia/resumen')
      ? { days: 7, priced: false, total: { ...bloque, calls: 0 }, by_domain: {}, by_use: {}, tools: [] } : { total: 0, items: [] }));
    renderWithApp(<IaWrapper />);
    expect(await screen.findByText(/El costo no se estima hasta configurar el precio/)).toBeInTheDocument();
  });
});

function IaWrapper() {
  return <AiPage />;
}

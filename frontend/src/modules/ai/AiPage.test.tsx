import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearApiCache } from '../../lib/useApi';
import { renderWithApp } from '../../test/render';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), del: vi.fn() }));
vi.mock('../../lib/api', () => api);

const { AiPage } = await import('./AiPage');

const bloque = { calls: 4, errors: 1, input_tokens: 32000, output_tokens: 1800, cost_usd: 0.0196, p50_ms: 8200, p95_ms: 9800 };

describe('Plataforma → IA', () => {
  beforeEach(() => clearApiCache());

  it('muestra costo, latencia por dominio y abre una traza con sus pasos', async () => {
    api.get.mockImplementation(async (path: string) => {
      if (path.startsWith('/api/ia/resumen')) return { days: 7, priced: true, total: bloque, by_domain: { operacion: bloque }, by_use: { 'incidente.diagnostico': bloque }, tools: [{ name: 'estado_cluster', calls: 3, errors: 0 }] };
      if (path.startsWith('/api/ia/evals')) return { runs: [{ at: '2026-11-09T07:10:00Z', model: 'gemini-3.5-flash', run: '1',
        suites: [{ suite: 'dominios', cases: 5, passed: 4, accuracy: 0.8, target: 0.9, invented_numbers: 1 }] }] };
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
    expect(await screen.findByText('IA de los dominios')).toBeInTheDocument();
    expect(screen.getByText('80 % · objetivo 90 %')).toBeInTheDocument();
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

describe('Plataforma → IA · Acceso MCP', () => {
  beforeEach(() => clearApiCache());

  it('el administrador emite un token, lo ve una sola vez con el comando de Claude Code y lo revoca', async () => {
    const vigente = { id: 'ab12', nombre: 'claude-code', creado_por: 'ana@x', creado: '2026-11-09T00:00:00Z', vence: '2099-01-01T00:00:00Z', ultimo_uso: null, revocado: null };
    let tokens: unknown[] = [];
    api.get.mockImplementation(async (path: string) => {
      if (path.startsWith('/api/ia/resumen')) return { days: 7, priced: false, total: { ...bloque, calls: 0 }, by_domain: {}, by_use: {}, tools: [], mcp: { calls: 3, errors: 1 } };
      if (path.startsWith('/api/ia/mcp/tokens')) return { items: tokens };
      return { total: 0, items: [], runs: [] };
    });
    api.post.mockImplementation(async () => { tokens = [vigente]; return { ...vigente, token: 'cop_mcp_secreto' }; });
    api.del.mockResolvedValue({ revoked: 'ab12' });
    const { user } = renderWithApp(<IaWrapper />);
    expect(await screen.findByText(/3 llamada\(s\), 1 con error/)).toBeInTheDocument();
    await user.type(screen.getByLabelText('Nombre'), 'claude-code');
    await user.click(screen.getByRole('button', { name: 'Emitir token' }));
    expect(api.post).toHaveBeenCalledWith('/api/ia/mcp/tokens', { nombre: 'claude-code', dias: 30 });
    expect(await screen.findByText(/--header "Authorization: Bearer cop_mcp_secreto"/)).toBeInTheDocument();
    expect(await screen.findByText('Nunca')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Revocar' }));
    expect(api.del).toHaveBeenCalledWith('/api/ia/mcp/tokens/ab12');
  });

  it('un operador no emite tokens', async () => {
    api.get.mockImplementation(async (path: string) => (path.startsWith('/api/ia/resumen')
      ? { days: 7, priced: false, total: { ...bloque, calls: 0 }, by_domain: {}, by_use: {}, tools: [] } : { total: 0, items: [], runs: [] }));
    renderWithApp(<IaWrapper />, { role: 'operador' });
    expect(await screen.findByText('Los tokens los emite un administrador.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Emitir token' })).not.toBeInTheDocument();
  });
});

function IaWrapper() {
  return <AiPage />;
}

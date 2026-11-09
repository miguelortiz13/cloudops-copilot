import { useState } from 'react';
import { del, get, post } from '../../lib/api';
import { API_URL } from '../../lib/config';
import { useApi } from '../../lib/useApi';
import { dateTime, number } from '../../lib/format';
import { useApp } from '../../state/hooks';
import { Card, Empty, Notice, Section } from '../../components/ui';

interface Token { id: string; nombre: string; creado_por: string; creado: string; vence: string; ultimo_uso: string | null; revocado: string | null }

/**
 * Acceso MCP (plan 11, hito IA-3): tokens de Lector para que Claude Code y otros agentes consulten la plataforma
 * con las mismas herramientas de solo lectura del chat. El token se muestra una sola vez.
 */
export function McpSection({ llamadas }: { llamadas?: { calls: number; errors: number } }) {
  const { can, toast } = useApp();
  const admin = can('administrador');
  const { data, reload } = useApi<{ items: Token[] }>('ia-mcp-tokens', () => (admin ? get('/api/ia/mcp/tokens') : Promise.resolve({ items: [] })));
  const [nombre, setNombre] = useState('');
  const [dias, setDias] = useState(30);
  const [nuevo, setNuevo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ahora = new Date().toISOString();
  const tokens = (data?.items ?? []).filter((t) => !t.revocado && t.vence > ahora);
  const comando = (token: string) => `claude mcp add --transport http cloudops ${API_URL}/mcp --header "Authorization: Bearer ${token}"`;

  const emitir = async () => {
    setError(null);
    try {
      const t = await post<Token & { token: string }>('/api/ia/mcp/tokens', { nombre: nombre.trim(), dias });
      setNuevo(t.token);
      setNombre('');
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  const revocar = async (t: Token) => {
    try {
      await del(`/api/ia/mcp/tokens/${t.id}`);
      toast(`Token ${t.nombre} revocado`);
      reload();
    } catch (e) {
      toast(`No se pudo revocar: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <Section title="Acceso MCP" description={`Claude Code y otros agentes consultan inventario, costos, hallazgos, cumplimiento, incidentes y Kubernetes con las herramientas de solo lectura del chat, con rol Lector. Cada llamada queda en la auditoría y deja su traza.${llamadas ? ` En el periodo: ${number(llamadas.calls)} llamada(s), ${number(llamadas.errors)} con error.` : ''}`}>
      <Card>
        <div className="stack" style={{ gap: 12 }}>
          {!admin ? <span className="secondary">Los tokens los emite un administrador.</span> : (
            <>
              <div className="row-actions" style={{ alignItems: 'flex-end', flexWrap: 'wrap' }}>
                <label className="field" style={{ flex: '1 1 220px' }}>
                  Nombre
                  <input className="input" value={nombre} maxLength={80} placeholder="claude-code de Ana" onChange={(e) => setNombre(e.target.value)} />
                </label>
                <label className="field">
                  Vence en
                  <select className="select" value={dias} onChange={(e) => setDias(Number(e.target.value))}>
                    {[7, 30, 90].map((d) => <option key={d} value={d}>{d} días</option>)}
                  </select>
                </label>
                <button className="btn btn-primary btn-sm" disabled={!nombre.trim()} onClick={emitir}>Emitir token</button>
              </div>
              {error && <Notice tone="critical">{error}</Notice>}
              {nuevo && (
                <Notice>
                  <div className="stack" style={{ gap: 8 }}>
                    <span>Cópialo ahora: no se vuelve a mostrar. Para conectarlo desde Claude Code:</span>
                    <code className="mono" style={{ fontSize: 12, wordBreak: 'break-all' }}>{comando(nuevo)}</code>
                    <div className="row-actions">
                      <button className="btn btn-sm" onClick={() => navigator.clipboard.writeText(comando(nuevo)).then(() => toast('Comando copiado'))}>Copiar comando</button>
                      <button className="btn btn-ghost btn-sm" onClick={() => setNuevo(null)}>Listo</button>
                    </div>
                  </div>
                </Notice>
              )}
              {tokens.length === 0 ? <Empty>No hay tokens vigentes.</Empty> : (
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>Nombre</th><th>Emitido por</th><th>Vence</th><th>Último uso</th><th /></tr></thead>
                    <tbody>
                      {tokens.map((t) => (
                        <tr key={t.id}>
                          <td>{t.nombre}</td>
                          <td className="secondary">{t.creado_por}</td>
                          <td className="secondary" style={{ whiteSpace: 'nowrap' }}>{dateTime(t.vence)}</td>
                          <td className="secondary" style={{ whiteSpace: 'nowrap' }}>{t.ultimo_uso ? dateTime(t.ultimo_uso) : 'Nunca'}</td>
                          <td><button className="btn btn-ghost btn-sm" onClick={() => revocar(t)}>Revocar</button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </Card>
    </Section>
  );
}

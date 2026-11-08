import { get } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime } from '../../lib/format';
import { Card, Section } from '../../components/ui';

interface Chequeo { url: string; ok: boolean | null; status?: number | null; ms?: number | null; error?: string | null; fallas?: number; abierta?: boolean; at?: string }

/** Última respuesta de cada URL de Chequeos HTTP (las revisa k8s-watch cada 10 minutos). */
export function ChecksStatus({ version }: { version: number }) {
  const { data } = useApi<{ items: Chequeo[] }>(`checks-${version}`, () => get('/api/checks'));
  if (!data?.items?.length) return null;
  return (
    <Section title="Estado de los chequeos" description="Última respuesta de cada URL.">
      <Card flush>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>URL</th><th>Resultado</th><th className="num">Tiempo</th><th>Revisada</th></tr></thead>
            <tbody>
              {data.items.map((c) => (
                <tr key={c.url}>
                  <td className="mono" style={{ fontSize: 12, wordBreak: 'break-all' }}>{c.url}</td>
                  <td>
                    {c.ok === null ? <span className="secondary">Sin revisar todavía</span> : (
                      <span className="badge"><span className={`dot ${c.ok ? 'dot-good' : 'dot-critical'}`} aria-hidden="true" />
                        {c.ok ? `Responde (${c.status})` : `${c.error}${c.abierta ? ' · incidente abierto' : ` · ${c.fallas} falla(s)`}`}</span>
                    )}
                  </td>
                  <td className="num">{c.ms != null ? `${c.ms} ms` : '—'}</td>
                  <td className="secondary" style={{ whiteSpace: 'nowrap' }}>{c.at ? dateTime(c.at) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </Section>
  );
}

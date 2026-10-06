import { useState } from 'react';
import { Download, Send } from 'lucide-react';
import { get, post, downloadUrl } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import type { Snapshot } from '../../lib/types';
import { useApp } from '../../state/hooks';
import { Card, Empty, Notice, PageHeader, Section, Segmented } from '../../components/ui';

function readWebhook(): string {
  try {
    return localStorage.getItem('teamsWebhookUrl') ?? '';
  } catch {
    return '';
  }
}

export function ReportsPage({ onSync }: { onSync: () => void }) {
  const { toast } = useApp();
  const snapshots = useApi<Snapshot[]>('snapshots', () => get('/api/inventory/snapshots'));
  const [webhook, setWebhook] = useState(readWebhook);
  const [kind, setKind] = useState<'all' | 'finops' | 'secops'>('all');
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  const saveWebhook = (v: string) => {
    setWebhook(v);
    try { localStorage.setItem('teamsWebhookUrl', v); } catch { /* almacenamiento no disponible */ }
  };

  const send = async () => {
    setSending(true);
    setResult(null);
    try {
      const r = await post<{ message: string }>('/api/integration/test-webhook', { webhook_url: webhook, alert_type: kind });
      setResult({ ok: true, text: r.message });
      toast('Alerta enviada a Teams');
    } catch (e) {
      setResult({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setSending(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Reportes y automatización"
        description="Inventario maestro en Excel, snapshots semanales y alertas a Microsoft Teams."
      />
      <div className="grid grid-2">
        <Section title="Inventario maestro" description="Excel con las revisiones manuales del equipo, actualizado por el pipeline de inventario.">
          <Card
            footer={<><span>El pipeline también clasifica los activos para ISO 27001.</span><button className="btn btn-sm" onClick={onSync}>Ejecutar pipeline</button></>}
          >
            <div className="spread">
              <div>
                <div className="card-title">Azure_IaC_Inventario.xlsx</div>
                <div className="card-subtitle">Hojas de análisis, priorización, trazabilidad e ISO</div>
              </div>
              <a className="btn btn-primary" href={downloadUrl('Azure_IaC_Inventario.xlsx')}><Download size={14} /> Descargar</a>
            </div>
          </Card>
          <Card title="Snapshots semanales" flush>
            {snapshots.data?.length ? (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Archivo</th><th>Fecha</th><th className="num">Tamaño</th><th /></tr></thead>
                  <tbody>
                    {snapshots.data.map((s) => (
                      <tr key={s.filename}>
                        <td className="mono" style={{ fontSize: 12 }}>{s.filename}</td>
                        <td className="secondary">{s.created_at}</td>
                        <td className="num secondary">{(s.size / 1024).toFixed(0)} KB</td>
                        <td><div className="row-actions"><a className="btn btn-ghost btn-sm btn-icon" href={downloadUrl(s.filename)} aria-label={`Descargar ${s.filename}`}><Download size={14} /></a></div></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <Empty>Aún no hay snapshots. Se generan cada vez que corre el pipeline.</Empty>}
          </Card>
        </Section>

        <Section title="Alertas a Microsoft Teams" description="Envía un resumen con cifras reales a un webhook entrante de un canal.">
          <Card>
            <div className="stack">
              <label className="stack" style={{ gap: 4 }}>
                <span className="muted" style={{ fontSize: 12 }}>URL del webhook</span>
                <input className="input" placeholder="https://…webhook.office.com/…" value={webhook} onChange={(e) => saveWebhook(e.target.value)} />
              </label>
              <div className="spread">
                <Segmented label="Tipo de alerta" value={kind} onChange={setKind} options={[
                  { id: 'all', label: 'Resumen' }, { id: 'finops', label: 'Costos' }, { id: 'secops', label: 'Seguridad' },
                ]} />
                <button className="btn btn-primary" disabled={!webhook || sending} onClick={send}>
                  <Send size={14} /> {sending ? 'Enviando…' : 'Enviar'}
                </button>
              </div>
              {result && <Notice tone={result.ok ? 'info' : 'critical'}>{result.text}</Notice>}
              <span className="muted" style={{ fontSize: 12.5 }}>La URL se guarda solo en este navegador.</span>
            </div>
          </Card>
        </Section>
      </div>
    </>
  );
}

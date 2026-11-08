import { useState } from 'react';
import { Sparkles } from 'lucide-react';
import { del, post } from '../../lib/api';
import { dateTime } from '../../lib/format';
import type { ControlException } from '../../lib/types';
import { useApp } from '../../state/hooks';
import { Notice } from '../../components/ui';

function enDias(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

/**
 * Excepción de un control (fase 3 del plan 10): la vigente con su revocación, o el formulario para pedir una,
 * con un borrador de la justificación redactado por la IA a partir de la evidencia del control.
 */
export function ExceptionPanel({ framework, control, exception, puedeExceptuar, onCambio }: {
  framework: string; control: string; exception: ControlException | null | undefined; puedeExceptuar: boolean; onCambio: () => void;
}) {
  const { can, toast } = useApp();
  const [abierto, setAbierto] = useState(false);
  const [texto, setTexto] = useState('');
  const [hasta, setHasta] = useState(enDias(90));
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const operador = can('operador');

  const accion = async (fn: () => Promise<unknown>, ok: string) => {
    setEnviando(true);
    setError(null);
    try {
      await fn();
      toast(ok);
      setAbierto(false);
      onCambio();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setEnviando(false);
    }
  };

  const borrador = async () => {
    setEnviando(true);
    setError(null);
    try {
      const r = await post<{ justification: string }>('/api/riesgo/excepciones/borrador', { framework, control });
      setTexto(r.justification);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setEnviando(false);
    }
  };

  if (exception) {
    return (
      <div className="stack" style={{ gap: 8 }}>
        <div className="subhead">Excepción vigente</div>
        <Notice tone="warning">
          Exceptuado hasta el <strong>{exception.until}</strong> por {exception.created_by} ({dateTime(exception.created_at)}). {exception.justification}
        </Notice>
        {operador && (
          <div><button className="btn btn-sm" disabled={enviando} onClick={() => accion(() => del(`/api/riesgo/excepciones/${exception.id}`), 'Excepción revocada')}>Revocar la excepción</button></div>
        )}
        {error && <Notice tone="critical">{error}</Notice>}
      </div>
    );
  }
  if (!puedeExceptuar || !operador) return null;
  if (!abierto) return <div><button className="btn btn-sm" onClick={() => setAbierto(true)}>Exceptuar este control…</button></div>;

  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="subhead">Exceptuar el control</div>
      <label className="field">
        Justificación (obligatoria)
        <textarea className="input textarea" value={texto} maxLength={2000} onChange={(e) => setTexto(e.target.value)}
          placeholder="Por qué hoy no se cumple, qué riesgo queda, qué lo mitiga y qué se hará antes del vencimiento" />
        <span className="hint">Al menos 20 caracteres. El borrador de la IA usa la evidencia del control: revísalo y completa lo que marque.</span>
      </label>
      <label className="field">
        Vence el
        <input className="input" type="date" min={enDias(1)} max={enDias(365)} value={hasta} onChange={(e) => setHasta(e.target.value)} />
        <span className="hint">Hasta un año. Al vencer, el control vuelve a su estado real.</span>
      </label>
      {error && <Notice tone="critical">{error}</Notice>}
      <div className="row-actions" style={{ justifyContent: 'flex-start' }}>
        <button className="btn btn-sm" disabled={enviando} onClick={borrador}><Sparkles size={14} /> Borrador con IA</button>
        <button className="btn btn-primary btn-sm" disabled={enviando || texto.trim().length < 20 || !hasta}
          onClick={() => accion(() => post('/api/riesgo/excepciones', { framework, control, justification: texto, until: hasta }), 'Control exceptuado')}>
          Aprobar la excepción
        </button>
        <button className="btn btn-sm" onClick={() => setAbierto(false)}>Cancelar</button>
      </div>
    </div>
  );
}

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { NAV } from './nav';
import {
  ChevronDown, Cloud, Menu, MessageSquare, Monitor, Moon, RefreshCw, Send, Sun, X,
} from 'lucide-react';
import { USER_INITIALS, USER_NAME, USER_ROLE } from '../lib/config';
import { get, post } from '../lib/api';
import { Markdown } from '../lib/markdown';
import type { SyncStatus } from '../lib/types';
import { useApp, type AgentType, type Theme } from '../state/hooks';
import { Modal } from './ui';

// ------------------------------------------------------------------ Sidebar


export function Sidebar({ active, mobileOpen, onNavigate }: {
  active: string;
  mobileOpen: boolean;
  onNavigate: () => void;
}) {
  const { setDockOpen, can } = useApp();
  return (
    <aside className={`sidebar ${mobileOpen ? 'is-mobile-open' : ''}`}>
      <div className="brand">
        <div className="brand-mark"><Cloud size={16} /></div>
        <div>
          <div className="brand-name">CloudOps Copilot</div>
          <div className="brand-sub">Operaciones cloud en Azure</div>
        </div>
      </div>
      <nav className="nav" aria-label="Secciones">
        {NAV.map((g) => (
          <div key={g.group}>
            <div className="nav-group-label">{g.group}</div>
            {g.items.filter((it) => !it.role || can(it.role)).map((it) => (
              <a
                key={it.id}
                href={`#/${it.id}`}
                className={`nav-item ${active === it.id ? 'is-active' : ''}`}
                aria-current={active === it.id ? 'page' : undefined}
                onClick={onNavigate}
              >
                {it.icon}
                {it.label}
              </a>
            ))}
          </div>
        ))}
        <button className="nav-item" onClick={() => { setDockOpen(true); onNavigate(); }}>
          <MessageSquare size={16} />
          Agentes de IA
        </button>
      </nav>
      <UserCard />
    </aside>
  );
}

const ROLE_LABEL = { lector: 'Lector', operador: 'Operador', administrador: 'Administrador' } as const;

function UserCard() {
  const { me } = useApp();
  const name = me?.name || USER_NAME;
  const initials = me?.name ? me.name.split(/\s+/).map((p) => p[0]).join('').slice(0, 2).toUpperCase() : USER_INITIALS;
  return (
    <div className="sidebar-foot" title={me?.upn || undefined}>
      <div className="avatar">{initials}</div>
      <div style={{ minWidth: 0 }}>
        <div className="user-name truncate">{name}</div>
        <div className="user-role truncate">
          {me ? ROLE_LABEL[me.role] : USER_ROLE}
          {me && !me.auth_enabled ? ' · sin autenticación' : ''}
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Topbar

function useClickOutside(ref: React.RefObject<HTMLElement | null>, onOutside: () => void) {
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onOutside();
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [ref, onOutside]);
}

function ScopeSelector() {
  const { subscriptions, selected, setSelected, subscriptionsLoaded } = useApp();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useClickOutside(ref, () => setOpen(false));

  const label = !subscriptionsLoaded
    ? 'Cargando…'
    : selected.length === subscriptions.length
      ? `Todas las suscripciones (${subscriptions.length})`
      : selected.length === 1
        ? subscriptions.find((s) => s.subscriptionId === selected[0])?.displayName ?? '1 suscripción'
        : `${selected.length} de ${subscriptions.length} suscripciones`;

  const toggle = (id: string) => {
    if (selected.includes(id)) {
      // Siempre queda al menos una: un scope vacío no tiene datos que mostrar.
      if (selected.length > 1) setSelected(selected.filter((s) => s !== id));
    } else {
      setSelected([...selected, id]);
    }
  };

  return (
    <div style={{ position: 'relative' }} ref={ref}>
      <button className="btn" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="truncate" style={{ maxWidth: 240 }}>{label}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="popover">
          <div className="popover-head">
            <span>Alcance</span>
            <button className="link-btn" onClick={() => setSelected(subscriptions.map((s) => s.subscriptionId))}>
              Seleccionar todas
            </button>
          </div>
          {subscriptions.map((s) => (
            <label key={s.subscriptionId} className="popover-item">
              <input
                type="checkbox"
                checked={selected.includes(s.subscriptionId)}
                onChange={() => toggle(s.subscriptionId)}
                style={{ accentColor: 'var(--accent)' }}
              />
              <div style={{ minWidth: 0 }}>
                <div className="truncate">{s.displayName}</div>
                <div className="mono muted" style={{ fontSize: 11 }}>{s.subscriptionId.slice(0, 8)}…</div>
              </div>
            </label>
          ))}
          {subscriptionsLoaded && !subscriptions.length && (
            <div className="empty">La identidad no ve ninguna suscripción.</div>
          )}
        </div>
      )}
    </div>
  );
}

const THEMES: { id: Theme; icon: ReactNode; label: string }[] = [
  { id: 'light', icon: <Sun size={15} />, label: 'Tema claro' },
  { id: 'dark', icon: <Moon size={15} />, label: 'Tema oscuro' },
  { id: 'system', icon: <Monitor size={15} />, label: 'Tema del sistema' },
];

function ThemeToggle() {
  const { theme, setTheme } = useApp();
  const i = THEMES.findIndex((t) => t.id === theme);
  const next = THEMES[(i + 1) % THEMES.length];
  return (
    <button className="btn btn-ghost btn-icon" onClick={() => setTheme(next.id)} title={`${THEMES[i].label} · cambiar a ${next.label.toLowerCase()}`} aria-label="Cambiar tema">
      {THEMES[i].icon}
    </button>
  );
}

function HealthIndicator() {
  const [ok, setOk] = useState<boolean | null>(null);
  useEffect(() => {
    const check = () =>
      get<{ azureConnected: boolean }>('/api/inventory/health')
        .then((r) => setOk(r.azureConnected))
        .catch(() => setOk(false));
    check();
    const t = setInterval(check, 60000);
    return () => clearInterval(t);
  }, []);
  if (ok === null) return null;
  return (
    <span className="badge" title={ok ? 'El API está conectado a Azure' : 'El API no responde o no tiene conexión con Azure'}>
      <span className={`dot ${ok ? 'dot-good' : 'dot-critical'}`} />
      {ok ? 'Conectado' : 'Sin conexión'}
    </span>
  );
}

export function Topbar({ trail, onMenu, onSync }: { trail: string[]; onMenu: () => void; onSync: () => void }) {
  const { setDockOpen, can } = useApp();
  return (
    <header className="topbar">
      <button className="btn btn-ghost btn-icon mobile-only" onClick={onMenu} aria-label="Menú"><Menu size={18} /></button>
      <div className="breadcrumb">
        {trail.map((t, i) => (
          <span key={i} className="row" style={{ gap: 8 }}>
            {i > 0 && <span aria-hidden="true">/</span>}
            {i === trail.length - 1 ? <strong>{t}</strong> : <span>{t}</span>}
          </span>
        ))}
      </div>
      <div className="topbar-actions">
        <HealthIndicator />
        <ScopeSelector />
        <button
          className="btn"
          onClick={onSync}
          disabled={!can('operador')}
          title={can('operador') ? 'Ejecutar el pipeline de inventario' : 'Requiere el rol Operador'}
        >
          <RefreshCw size={14} /> Sincronizar
        </button>
        <button className="btn" onClick={() => setDockOpen(true)}>
          <MessageSquare size={14} /> Agentes
        </button>
        <ThemeToggle />
      </div>
    </header>
  );
}

// ------------------------------------------------------------------ Sync

export function SyncDialog({ onClose }: { onClose: () => void }) {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelado = false;
    post<{ status: string }>('/api/sync', {}).catch((e) => setError(String(e.message || e)));
    const poll = () =>
      get<SyncStatus>('/api/sync/status').then((s) => !cancelado && setStatus(s)).catch(() => undefined);
    poll();
    const t = setInterval(poll, 3000);
    return () => { cancelado = true; clearInterval(t); };
  }, []);

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' });
  }, [status?.logs]);

  return (
    <Modal
      title="Pipeline de inventario"
      subtitle="Exporta el inventario a Azure Resource Graph, actualiza el Excel maestro y genera el snapshot semanal."
      onClose={onClose}
      footer={<button className="btn" onClick={onClose}>Cerrar</button>}
    >
      <div className="row">
        {status?.running ? <div className="spinner" /> : <span className={`dot ${status?.error ? 'dot-critical' : 'dot-good'}`} />}
        <span className="secondary">
          {error ? `No se pudo iniciar: ${error}` : status?.running ? 'En ejecución…' : status?.error ? status.error : `Última ejecución: ${status?.last_run ?? '—'}`}
        </span>
      </div>
      <pre className="console">{status?.logs ?? 'Esperando el registro…'}<div ref={end} /></pre>
      <span className="muted" style={{ fontSize: 12.5 }}>Puedes cerrar esta ventana: el pipeline sigue en segundo plano.</span>
    </Modal>
  );
}

// ------------------------------------------------------------------ Agent dock

const AGENTS: { id: AgentType; label: string; desc: string; suggestions: string[] }[] = [
  {
    id: 'inventory', label: 'Inventario', desc: 'Recursos, tags y gobernanza',
    suggestions: ['Dame un resumen del inventario', '¿Qué recursos incumplen la política de tags?'],
  },
  {
    id: 'finops', label: 'Costos', desc: 'Gasto, atribución y ahorro',
    suggestions: ['¿En qué se va la mayor parte del gasto?', '¿Cuáles son las oportunidades de ahorro?'],
  },
  {
    id: 'secops', label: 'Seguridad', desc: 'Exposición y salud operativa',
    suggestions: ['¿Qué debo remediar primero?', '¿Qué recursos están expuestos a internet?'],
  },
  {
    id: 'k8s', label: 'Kubernetes', desc: 'Diagnóstico de clústeres AKS',
    suggestions: ['Hazme un diagnóstico del clúster', '¿Qué pods tienen problemas?'],
  },
];

interface Message {
  id: string;
  from: 'user' | 'bot';
  text: string;
  time: string;
  mode?: string;
}

const now = () => new Date().toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' });

export function AgentDock() {
  const { dockOpen, setDockOpen, dockAgent, setDockAgent, pendingQuestion, scope, can } = useApp();
  const [histories, setHistories] = useState<Record<AgentType, Message[]>>({
    inventory: [], finops: [], secops: [], k8s: [],
  });
  const [typing, setTyping] = useState<AgentType | null>(null);
  const [input, setInput] = useState('');
  const end = useRef<HTMLDivElement>(null);
  const agent = AGENTS.find((a) => a.id === dockAgent)!;
  const messages = histories[dockAgent];

  const send = async (agentId: AgentType, text: string) => {
    if (!text.trim()) return;
    const push = (m: Message) => setHistories((h) => ({ ...h, [agentId]: [...h[agentId], m] }));
    push({ id: crypto.randomUUID(), from: 'user', text, time: now() });
    setInput('');
    setTyping(agentId);
    try {
      const r = agentId === 'k8s'
        ? await post<{ answer: string; mode: string }>('/api/k8s/chat', { message: text })
        : await post<{ answer: string; mode: string }>('/api/chat', { message: text, agent_type: agentId, subscriptions: scope });
      push({ id: crypto.randomUUID(), from: 'bot', text: r.answer, time: now(), mode: r.mode });
    } catch (e) {
      // Sin respuesta del API no se inventa una: se dice qué pasó.
      push({
        id: crypto.randomUUID(), from: 'bot', time: now(), mode: 'error',
        text: `No pude obtener respuesta del API: ${e instanceof Error ? e.message : String(e)}`,
      });
    } finally {
      setTyping(null);
    }
  };

  // Otra vista pidió preguntar algo al agente: se trata como un evento externo.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (pendingQuestion) send(pendingQuestion.agent, pendingQuestion.text);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingQuestion?.id]);

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' });
  }, [messages.length, typing]);

  return (
    <aside className={`dock ${dockOpen ? 'is-open' : ''}`} aria-hidden={!dockOpen} aria-label="Agentes de IA">
      <div className="dock-head">
        <div className="dock-title">
          <div>
            <div className="card-title">Agentes de IA</div>
            <div className="card-subtitle">{agent.desc}</div>
          </div>
          <button className="btn btn-ghost btn-icon" onClick={() => setDockOpen(false)} aria-label="Cerrar"><X size={16} /></button>
        </div>
        <div className="segmented" role="tablist" aria-label="Agente">
          {AGENTS.map((a) => {
            // El agente de Kubernetes ejecuta comandos en el clúster: solo operadores.
            const bloqueado = a.id === 'k8s' && !can('operador');
            return (
              <button
                key={a.id}
                className={dockAgent === a.id ? 'is-active' : ''}
                onClick={() => setDockAgent(a.id)}
                disabled={bloqueado}
                title={bloqueado ? 'Requiere el rol Operador' : undefined}
              >
                {a.label}
              </button>
            );
          })}
        </div>
      </div>
      <div className="dock-messages">
        {messages.length === 0 && (
          <div className="empty" style={{ padding: '24px 8px' }}>
            <strong>Agente de {agent.label.toLowerCase()}</strong>
            Responde con los mismos datos y reglas que muestra el panel, sobre las suscripciones del alcance actual.
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`msg ${m.from === 'user' ? 'msg-user' : 'msg-bot'}`}>
            <div className="msg-meta">
              {m.from === 'user' ? USER_NAME : `Agente de ${agent.label.toLowerCase()}`} · {m.time}
              {m.mode && m.from === 'bot' && (
                <> · {m.mode === 'error' ? 'error' : m.mode.includes('gemini') ? 'IA' : 'motor de reglas'}</>
              )}
            </div>
            <div className="msg-body">{m.from === 'bot' ? <Markdown text={m.text} /> : m.text}</div>
          </div>
        ))}
        {typing === dockAgent && (
          <div className="msg msg-bot">
            <div className="msg-body"><span className="typing"><span /><span /><span /></span></div>
          </div>
        )}
        <div ref={end} />
      </div>
      <div className="dock-input">
        <div className="chips">
          {agent.suggestions.map((s) => (
            <button key={s} className="chip" onClick={() => send(dockAgent, s)}>{s}</button>
          ))}
        </div>
        <form className="row" onSubmit={(e) => { e.preventDefault(); send(dockAgent, input); }}>
          <input
            className="input"
            style={{ flex: 1 }}
            placeholder={`Pregunta al agente de ${agent.label.toLowerCase()}…`}
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          <button className="btn btn-primary btn-icon" type="submit" disabled={!input.trim()} aria-label="Enviar">
            <Send size={14} />
          </button>
        </form>
      </div>
    </aside>
  );
}

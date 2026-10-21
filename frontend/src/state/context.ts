import { createContext } from 'react';
import type { CloudAccount, Me, Role, Subscription } from '../lib/types';

export type AgentType = 'inventory' | 'finops' | 'secops' | 'k8s';
export type Theme = 'light' | 'dark' | 'system';

export interface Toast {
  id: number;
  text: string;
}

export interface AppState {
  /** Suscripciones de Azure visibles para la identidad de la plataforma (vistas en vivo). */
  subscriptions: Subscription[];
  subscriptionsLoaded: boolean;
  /** Cuentas de todas las nubes (azure:sub/…, aws:account/…) con su nube. */
  accounts: CloudAccount[];
  providerLabels: Record<string, string>;
  /** uids de cuenta elegidos en el filtro del panel. */
  selected: string[];
  setSelected: (uids: string[]) => void;
  /**
   * Suscripciones de Azure del filtro para las vistas en vivo: vacío cuando
   * están todas, para que el backend resuelva "todas" sin una lista larga.
   */
  scope: string[];
  /** Clave estable del scope, para las cachés de datos. */
  scopeKey: string;
  /** El filtro no incluye ninguna suscripción de Azure: las vistas en vivo no tienen qué mostrar. */
  azureNone: boolean;
  /** uids del filtro para las vistas de la base; vacío = todas las cuentas. */
  accountScope: string[];
  accountKey: string;
  /** Si una cuenta entra en el filtro. */
  inScope: (accountUid: string | null | undefined) => boolean;
  theme: Theme;
  setTheme: (t: Theme) => void;
  toast: (text: string) => void;
  toasts: Toast[];
  dockOpen: boolean;
  setDockOpen: (open: boolean) => void;
  dockAgent: AgentType;
  setDockAgent: (agent: AgentType) => void;
  /** Abre la consola en un agente y, si se pasa, envía la pregunta. */
  askAgent: (agent: AgentType, question?: string) => void;
  pendingQuestion: { agent: AgentType; text: string; id: number } | null;
  /** Usuario actual; null mientras carga. */
  me: Me | null;
  /** Si el usuario tiene al menos ese rol. Mientras carga, no. */
  can: (role: Role) => boolean;
}


export const Ctx = createContext<AppState | null>(null);

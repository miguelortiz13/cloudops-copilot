import { createContext } from 'react';
import type { Subscription } from '../lib/types';

export type AgentType = 'inventory' | 'finops' | 'secops' | 'k8s';
export type Theme = 'light' | 'dark' | 'system';

export interface Toast {
  id: number;
  text: string;
}

export interface AppState {
  /** Suscripciones visibles para la identidad de la plataforma. */
  subscriptions: Subscription[];
  subscriptionsLoaded: boolean;
  /** Suscripciones elegidas por el usuario. */
  selected: string[];
  setSelected: (ids: string[]) => void;
  /**
   * Scope que se envía al API: vacío cuando están todas seleccionadas, para
   * que el backend resuelva "todas" sin una lista larga en la URL.
   */
  scope: string[];
  /** Clave estable del scope, para las cachés de datos. */
  scopeKey: string;
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
}


export const Ctx = createContext<AppState | null>(null);

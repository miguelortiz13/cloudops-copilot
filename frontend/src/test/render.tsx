import type { ReactElement } from 'react';
import { render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import { Ctx, type AppState } from '../state/context';
import type { Role } from '../lib/types';
import { me, subscriptions } from './fixtures';

/** Estado de la aplicación para un usuario con `role`; las acciones son espías. */
export function appState(role: Role = 'administrador', over: Partial<AppState> = {}): AppState {
  const usuario = me(role);
  const subs = subscriptions.subscriptions;
  return {
    subscriptions: subs, subscriptionsLoaded: true, selected: subs.map((s) => s.subscriptionId), setSelected: vi.fn(),
    scope: [], scopeKey: 'all', theme: 'light', setTheme: vi.fn(), toast: vi.fn(), toasts: [],
    dockOpen: false, setDockOpen: vi.fn(), dockAgent: 'inventory', setDockAgent: vi.fn(), askAgent: vi.fn(),
    pendingQuestion: null, me: usuario, can: (r: Role) => usuario.permissions[r],
    ...over,
  };
}

/** Renderiza dentro del contexto de la aplicación y devuelve también `user` y el estado. */
export function renderWithApp(ui: ReactElement, { role = 'administrador' as Role, state = {} as Partial<AppState> } = {}) {
  const app = appState(role, state);
  const user = userEvent.setup();
  return { user, app, ...render(<Ctx.Provider value={app}>{ui}</Ctx.Provider>) };
}

import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { renderWithApp } from '../../test/render';
import { AccionesSection } from './AccionesSection';

const acciones = [
  { id: 1, text: 'Fijar el tag de la imagen', owner: 'ana@x', created_by: 'ana@x', created_at: '2026-11-10T10:00:00Z', done_at: null },
  { id: 2, text: 'Alertar ImagePullBackOff', owner: null, created_by: 'ana@x', created_at: '2026-11-10T10:00:00Z', done_at: '2026-11-10T12:00:00Z' },
];

describe('Acciones de seguimiento del incidente', () => {
  it('crea desde el post-mortem, marca hecha y agrega a mano', async () => {
    const accion = vi.fn().mockResolvedValue(true);
    const { user } = renderWithApp(<AccionesSection actions={acciones} postmortem="**Acciones**\n- x" operador accion={accion} />);
    expect(screen.getByText(/1 abierta\(s\) de 2/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Crear desde el post-mortem' }));
    expect(accion).toHaveBeenCalledWith('actions', { from_postmortem: true }, expect.any(String));
    await user.click(screen.getByRole('checkbox', { name: /Fijar el tag/ }));
    expect(accion).toHaveBeenCalledWith('actions/1', { done: true }, 'Acción hecha');
    await user.type(screen.getByLabelText('Nueva acción'), 'Revisar límites de memoria');
    await user.click(screen.getByRole('button', { name: 'Agregar' }));
    expect(accion).toHaveBeenCalledWith('actions', { text: 'Revisar límites de memoria' }, 'Acción agregada');
  });

  it('sin acciones ni post-mortem no se muestra', () => {
    const { container } = renderWithApp(<AccionesSection actions={[]} postmortem={null} operador accion={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});

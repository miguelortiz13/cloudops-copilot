import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Delta, Drawer, Pagination, Segmented, SeverityBadge, Tabs } from './ui';

describe('componentes base', () => {
  it('Segmented es un grupo de radios accesible', async () => {
    const onChange = vi.fn();
    render(<Segmented label="Estado" value="a" onChange={onChange} options={[{ id: 'a', label: 'Activos' }, { id: 'b', label: 'Resueltos' }]} />);
    expect(screen.getByRole('radiogroup', { name: 'Estado' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Activos' })).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(screen.getByRole('radio', { name: 'Resueltos' }));
    expect(onChange).toHaveBeenCalledWith('b');
  });

  it('Tabs marca la pestaña activa y muestra el conteo', async () => {
    const onChange = vi.fn();
    render(<Tabs value="x" onChange={onChange} tabs={[{ id: 'x', label: 'Uno' }, { id: 'y', label: 'Dos', count: 4 }]} />);
    expect(screen.getByRole('tab', { name: 'Uno' })).toHaveAttribute('aria-selected', 'true');
    await userEvent.click(screen.getByRole('tab', { name: /Dos/ }));
    expect(onChange).toHaveBeenCalledWith('y');
    expect(screen.getByRole('tab', { name: /Dos/ })).toHaveTextContent('4');
  });

  it('Pagination: rango visible y botones en los extremos', async () => {
    const onPage = vi.fn();
    const { rerender } = render(<Pagination page={1} pageSize={50} total={120} onPage={onPage} />);
    expect(screen.getByText('1–50 de 120')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Anterior' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
    expect(onPage).toHaveBeenCalledWith(2);
    rerender(<Pagination page={3} pageSize={50} total={120} onPage={onPage} />);
    expect(screen.getByText('101–120 de 120')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Siguiente' })).toBeDisabled();
  });

  it('Drawer: nombre accesible por su título y se cierra con Escape', async () => {
    const onClose = vi.fn();
    render(<Drawer title="kv-pagos-prod" onClose={onClose}>contenido</Drawer>);
    expect(screen.getByRole('dialog', { name: 'kv-pagos-prod' })).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalled();
  });

  it('la severidad nunca es solo color: lleva su nombre', () => {
    render(<SeverityBadge severity="critica" />);
    expect(screen.getByText('Crítica')).toBeInTheDocument();
  });

  it('Delta: el signo y si es bueno o malo dependen de la polaridad', () => {
    const { container, rerender } = render(<Delta value={12.5} polarity="up-bad" />);
    expect(container.querySelector('.delta-bad')).toHaveTextContent('+12,5%');
    rerender(<Delta value={-3} polarity="up-bad" />);
    expect(container.querySelector('.delta-good')).toHaveTextContent('-3%');
    // Un cambio menor a 0,05 no es ni bueno ni malo.
    rerender(<Delta value={0.01} polarity="up-good" />);
    expect(container.querySelector('.delta-neutral')).not.toBeNull();
    rerender(<Delta value={null} />);
    expect(container.querySelector('.delta')).toBeNull();
  });
});

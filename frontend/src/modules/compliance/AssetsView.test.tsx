import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { classifiedAssets, manyAssets } from '../../test/fixtures';
import { renderWithApp } from '../../test/render';
import type { ClassifiedAsset } from '../../lib/types';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), download: vi.fn() }));
vi.mock('../../lib/api', () => api);

const { AssetsView } = await import('./AssetsView');

function abrir(nombre: string) {
  const fila = screen.getByText(nombre).closest('tr')!;
  return within(fila).getByRole('button', { name: 'Detalle' });
}

describe('Clasificación de activos', () => {
  beforeEach(() => {
    api.get.mockResolvedValue(classifiedAssets());
    api.post.mockReset();
    api.download.mockReset();
  });

  it('resume la clasificación y ordena por criticidad', async () => {
    renderWithApp(<AssetsView onGo={vi.fn()} />);
    expect(await screen.findByText('kv-pagos-prod')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/compliance/assets');
    const filas = screen.getAllByRole('row').slice(1);
    expect(within(filas[0]).getByText('kv-pagos-prod')).toBeInTheDocument();
    expect(within(filas[0]).getByText('3 · 3 · 3')).toBeInTheDocument();
    // Una clasificación manual se distingue de la automática.
    expect(screen.getByText('Restringido · manual')).toBeInTheDocument();
    expect(screen.getByText('1 fijado(s) a mano')).toBeInTheDocument();
  });

  it('filtra por clase, por custodio faltante y por texto', async () => {
    const { user } = renderWithApp(<AssetsView onGo={vi.fn()} />);
    await screen.findByText('kv-pagos-prod');
    await user.click(screen.getByRole('radio', { name: 'Sin custodio' }));
    expect(screen.getAllByRole('row').slice(1).map((r) => r.querySelector('.primary-cell')?.textContent))
      .toEqual(['nsg-pagos-prod', 'app-web-dev']);

    await user.click(screen.getByRole('radio', { name: 'Todos' }));
    await user.type(screen.getByPlaceholderText(/Buscar/), 'EQUIPO-WEB');
    expect(screen.getAllByRole('row')).toHaveLength(2);
    expect(screen.getByText('stwebdev01')).toBeInTheDocument();

    await user.clear(screen.getByPlaceholderText(/Buscar/));
    await user.type(screen.getByPlaceholderText(/Buscar/), 'no-existe');
    expect(screen.getByText('Ningún activo coincide.')).toBeInTheDocument();
  });

  it('pagina de 50 en 50 y vuelve a la primera página al filtrar', async () => {
    api.get.mockResolvedValue(classifiedAssets(manyAssets(70)));
    const { user } = renderWithApp(<AssetsView onGo={vi.fn()} />);
    await screen.findByText('kv-pagos-prod');
    expect(screen.getByText('1–50 de 75')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Siguiente' }));
    expect(screen.getByText('51–75 de 75')).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText(/Buscar/), 'lote-07');
    expect(screen.queryByRole('button', { name: 'Siguiente' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('row')).toHaveLength(2);
  });

  it('un operador clasifica a mano: exige motivo y envía la tríada elegida', async () => {
    const guardado: ClassifiedAsset = { ...classifiedAssets().items[3], classification: 'Restringido', method: 'manual', confidentiality: 2, integrity: 3, availability: 2, score: 7 };
    api.post.mockResolvedValue(guardado);
    const { user, app } = renderWithApp(<AssetsView onGo={vi.fn()} />, { role: 'operador' });
    await screen.findByText('app-web-dev');
    await user.click(abrir('app-web-dev'));
    const panel = screen.getByRole('dialog', { name: 'app-web-dev' });
    await user.click(within(panel).getByRole('button', { name: 'Cambiar clasificación' }));

    await user.selectOptions(within(panel).getByLabelText(/^Clasificación/), 'Restringido');
    // Elegir la clase propone su tríada; se puede ajustar.
    expect(within(panel).getByLabelText(/^Integridad/)).toHaveValue('2');
    await user.selectOptions(within(panel).getByLabelText(/^Integridad/), '3');
    await user.type(within(panel).getByLabelText(/^Custodio/), 'equipo-web');

    const guardar = within(panel).getByRole('button', { name: 'Guardar clasificación' });
    expect(guardar).toBeDisabled();
    await user.type(within(panel).getByLabelText(/^Motivo/), '  ');
    expect(guardar).toBeDisabled();
    await user.type(within(panel).getByLabelText(/^Motivo/), 'Expone datos personales de prueba');
    await user.click(guardar);

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(api.post).toHaveBeenCalledWith('/api/compliance/assets/classification', {
      resource_uid: classifiedAssets().items[3].uid, classification: 'Restringido',
      confidentiality: 2, integrity: 3, availability: 2, risk_required: false,
      reason: 'Expone datos personales de prueba', custodian: 'equipo-web',
    });
    expect(app.toast).toHaveBeenCalledWith('Clasificado como Restringido.');
  });

  it('un error del API se muestra en el panel y no se pierde lo escrito', async () => {
    api.post.mockRejectedValue(new Error('Cambiar la clasificación exige un motivo.'));
    const { user } = renderWithApp(<AssetsView onGo={vi.fn()} />, { role: 'operador' });
    await screen.findByText('app-web-dev');
    await user.click(abrir('app-web-dev'));
    const panel = screen.getByRole('dialog');
    await user.click(within(panel).getByRole('button', { name: 'Cambiar clasificación' }));
    await user.type(within(panel).getByLabelText(/^Motivo/), 'x');
    await user.click(within(panel).getByRole('button', { name: 'Guardar clasificación' }));
    expect(await within(panel).findByRole('alert')).toHaveTextContent('exige un motivo');
    expect(within(panel).getByLabelText(/^Motivo/)).toHaveValue('x');
  });

  it('restaurar la automática solo aparece en clasificaciones manuales', async () => {
    api.post.mockResolvedValue({ ...classifiedAssets().items[4], method: 'automatica' });
    const { user } = renderWithApp(<AssetsView onGo={vi.fn()} />, { role: 'operador' });
    await screen.findByText('stwebdev01');
    await user.click(abrir('kv-pagos-prod'));
    expect(screen.queryByRole('button', { name: 'Restaurar la automática' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cerrar' }));

    await user.click(abrir('stwebdev01'));
    await user.click(screen.getByRole('button', { name: 'Restaurar la automática' }));
    expect(api.post).toHaveBeenCalledWith('/api/compliance/assets/classification/restore', { resource_uid: classifiedAssets().items[4].uid });
  });

  it('un lector ve el detalle pero no puede cambiarlo', async () => {
    const { user } = renderWithApp(<AssetsView onGo={vi.fn()} />, { role: 'lector' });
    await screen.findByText('stwebdev01');
    await user.click(abrir('stwebdev01'));
    expect(screen.getByText('Cambiar la clasificación requiere el rol Operador.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cambiar clasificación' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Restaurar la automática' })).not.toBeInTheDocument();
  });

  it('el CSV se descarga con la sesión (no con un enlace sin token)', async () => {
    api.download.mockResolvedValue(undefined);
    const { user } = renderWithApp(<AssetsView onGo={vi.fn()} />, { role: 'lector' });
    await screen.findByText('kv-pagos-prod');
    await user.click(screen.getByRole('button', { name: /Exportar CSV/ }));
    expect(api.download).toHaveBeenCalledWith('/api/compliance/assets/export', undefined, 'activos-clasificados.csv');
  });

  it('sin base de datos lo explica en vez de mostrar una tabla vacía', async () => {
    api.get.mockRejectedValue(new Error('Historia no disponible: la base de datos no está configurada.'));
    renderWithApp(<AssetsView onGo={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('La clasificación no está disponible');
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeInTheDocument();
  });
});

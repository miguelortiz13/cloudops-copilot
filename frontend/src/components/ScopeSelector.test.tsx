import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { renderWithApp } from '../test/render';
import { AzureGuard } from './AzureGuard';
import { ScopeSelector } from './layout';

const cuentas = [
  { uid: 'azure:sub/a', provider: 'azure', native_id: 'a', name: 'Producción (demo)', visible: true },
  { uid: 'azure:sub/b', provider: 'azure', native_id: 'b', name: 'Laboratorio (demo)', visible: true },
  { uid: 'aws:account/111111111111', provider: 'aws', native_id: '111111111111', name: 'AWS (demo)', visible: true },
];
const etiquetas = { azure: 'Microsoft Azure', aws: 'Amazon Web Services' };

describe('Filtro por nube y cuenta', () => {
  it('agrupa las cuentas por nube y elige una nube entera', async () => {
    const { user, app } = renderWithApp(<ScopeSelector />, {
      state: { accounts: cuentas, providerLabels: etiquetas, selected: cuentas.map((c) => c.uid) },
    });
    await user.click(screen.getByRole('button', { name: /Todas las cuentas \(3\)/ }));
    expect(screen.getByRole('group', { name: 'Amazon Web Services' })).toHaveTextContent('AWS (demo)');
    // Desmarcar Azure deja solo AWS.
    await user.click(screen.getByRole('checkbox', { name: 'Microsoft Azure' }));
    expect(app.setSelected).toHaveBeenCalledWith(['aws:account/111111111111']);
  });

  it('nunca deja el alcance vacío y dice qué nube está elegida', async () => {
    const { user, app } = renderWithApp(<ScopeSelector />, {
      state: { accounts: cuentas, providerLabels: etiquetas, selected: ['aws:account/111111111111'] },
    });
    await user.click(screen.getByRole('button', { name: /AWS \(demo\)/ }));
    await user.click(screen.getByRole('checkbox', { name: /AWS \(demo\)/ }));
    expect(app.setSelected).not.toHaveBeenCalled();
  });

  it('las vistas en vivo de Azure no se montan sin suscripciones de Azure en el filtro', () => {
    renderWithApp(<AzureGuard><span>vista en vivo</span></AzureGuard>, { state: { azureNone: true } });
    expect(screen.queryByText('vista en vivo')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('no incluye ninguna suscripción de Azure');
  });
});

import { abrir, expect, test } from './mock-api';

test.describe('lector', () => {
  test.use({ role: 'lector' });

  test('no ve Administración y la ruta directa explica el permiso', async ({ page }) => {
    await abrir(page, 'resumen', 'Resumen');
    await expect(page.getByRole('navigation', { name: 'Secciones' }).getByText('Administración')).toHaveCount(0);
    await page.goto('/#/admin');
    await expect(page.getByText('Requiere el rol Administrador')).toBeVisible();
    await expect(page.getByText('Tu rol es Lector.', { exact: false })).toBeVisible();
  });

  test('no puede sincronizar ni clasificar', async ({ page }) => {
    await abrir(page, 'cumplimiento/activos', 'Cumplimiento');
    await expect(page.getByRole('button', { name: 'Sincronizar' })).toBeDisabled();
    await page.getByRole('row', { name: /stwebdev01/ }).getByRole('button', { name: 'Detalle' }).click();
    const panel = page.getByRole('dialog', { name: 'stwebdev01' });
    await expect(panel.getByText('Cambiar la clasificación requiere el rol Operador.')).toBeVisible();
    await expect(panel.getByRole('button', { name: 'Cambiar clasificación' })).toHaveCount(0);
  });
});

test.describe('operador', () => {
  test.use({ role: 'operador' });

  test('gestiona, pero Administración sigue cerrada', async ({ page }) => {
    await abrir(page, 'secops/gestion', 'Seguridad');
    await page.getByRole('row', { name: /kv-pagos-prod/ }).getByRole('button', { name: 'Gestionar' }).click();
    await expect(page.getByRole('dialog').getByRole('button', { name: 'Asumir' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sincronizar' })).toBeEnabled();
    await expect(page.getByRole('navigation', { name: 'Secciones' }).getByText('Administración')).toHaveCount(0);
  });
});

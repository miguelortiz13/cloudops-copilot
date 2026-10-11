import { abrir, expect, test } from './mock-api';

test.describe('Cumplimiento', () => {
  test.use({ role: 'administrador' });

  test('de un control que no cumple a la gestión de su hallazgo', async ({ page }) => {
    await abrir(page, 'cumplimiento/controles', 'Cumplimiento');
    await expect(page.getByRole('alert')).toContainText('Una regla no se pudo evaluar');
    await page.getByRole('radio', { name: 'No cumple (2)' }).click();
    await expect(page.getByRole('row')).toHaveCount(3);
    await page.getByRole('row', { name: /8\.7/ }).getByRole('button', { name: 'Detalle' }).click();
    const panel = page.getByRole('dialog', { name: 'CIS 8.7' });
    await expect(panel.getByText('Key Vault alcanzable desde red pública')).toBeVisible();
    await panel.getByRole('button', { name: 'Ir a la gestión de hallazgos' }).click();
    await expect(page).toHaveURL(/#\/secops\/gestion/);
    await expect(page.getByRole('tab', { name: 'Gestión de hallazgos' })).toHaveAttribute('aria-selected', 'true');
  });

  test('ISO: los controles de clasificación llevan a los activos', async ({ page }) => {
    await abrir(page, 'cumplimiento/controles', 'Cumplimiento');
    await page.getByRole('radio', { name: 'ISO 27001:2022' }).click();
    await page.getByRole('row', { name: /A\.5\.9/ }).getByRole('button', { name: 'Detalle' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Ver la clasificación de activos' }).click();
    await expect(page).toHaveURL(/#\/cumplimiento\/activos/);
    await expect(page.getByRole('row', { name: /kv-pagos-prod/ })).toBeVisible();
  });

  test('clasificar a mano queda en la tabla y en la auditoría', async ({ page, api }) => {
    await abrir(page, 'cumplimiento/activos', 'Cumplimiento');
    await page.getByRole('row', { name: /app-web-dev/ }).getByRole('button', { name: 'Detalle' }).click();
    const panel = page.getByRole('dialog', { name: 'app-web-dev' });
    await panel.getByRole('button', { name: 'Cambiar clasificación' }).click();
    await panel.getByLabel(/^Clasificación/).selectOption('Restringido');
    await panel.getByLabel(/^Disponibilidad/).selectOption('3');
    await panel.getByLabel(/^Custodio/).fill('equipo-web');
    await expect(panel.getByRole('button', { name: 'Guardar clasificación' })).toBeDisabled();
    await panel.getByLabel(/^Motivo/).fill('Expone formularios con datos personales');
    await panel.getByRole('button', { name: 'Guardar clasificación' }).click();

    await expect(page.locator('.toast')).toHaveText('Clasificado como Restringido.');
    await expect(panel.getByText('Restringido · manual')).toBeVisible();
    expect(api.lastBody('POST /api/compliance/assets/classification')).toMatchObject({
      classification: 'Restringido', confidentiality: 2, integrity: 2, availability: 3, custodian: 'equipo-web',
    });
    await panel.getByRole('button', { name: 'Cerrar' }).click();
    await expect(page.getByRole('row', { name: /app-web-dev/ })).toContainText('Restringido · manual');
    await expect(page.getByRole('row', { name: /app-web-dev/ })).toContainText('equipo-web');

    await page.goto('/#/admin/actividad');
    await page.getByRole('radio', { name: 'Clasificación' }).click();
    await expect(page.getByText('Clasificó un activo a mano').first()).toBeVisible();
    await expect(page.getByText('“Expone formularios con datos personales”', { exact: false })).toBeVisible();
  });

  test('restaurar la clasificación automática', async ({ page, api }) => {
    await abrir(page, 'cumplimiento/activos', 'Cumplimiento');
    await page.getByRole('row', { name: /stwebdev01/ }).getByRole('button', { name: 'Detalle' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Restaurar la automática' }).click();
    await expect(page.locator('.toast')).toHaveText('Clasificación automática restaurada.');
    expect(api.calls.some((c) => c.path === '/api/compliance/assets/classification/restore')).toBe(true);
    await expect(page.getByRole('dialog').getByRole('button', { name: 'Restaurar la automática' })).toHaveCount(0);
  });

  test('exportar el CSV descarga el archivo', async ({ page }) => {
    await abrir(page, 'cumplimiento/activos', 'Cumplimiento');
    const descarga = page.waitForEvent('download');
    await page.getByRole('button', { name: /Exportar CSV/ }).click();
    expect((await descarga).suggestedFilename()).toBe('activos-clasificados.csv');
  });
});

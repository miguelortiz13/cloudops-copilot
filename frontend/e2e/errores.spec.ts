import { abrir, expect, Respuesta, test } from './mock-api';

test.describe('sin base de datos', () => {
  test.use({
    overrides: {
      'GET /api/compliance': () => new Respuesta(503, { detail: 'Historia no disponible: la base de datos no está configurada.' }),
      'GET /api/findings': () => new Respuesta(503, { detail: 'Historia no disponible: la base de datos no está configurada.' }),
    },
    allowedConsoleErrors: [/503/],
  });

  test('Cumplimiento explica el motivo y ofrece reintentar', async ({ page, api }) => {
    await abrir(page, 'cumplimiento/controles', 'Cumplimiento');
    await expect(page.getByRole('alert')).toContainText('El cumplimiento no está disponible');
    await expect(page.getByRole('alert')).toContainText('la base de datos no está configurada');
    const antes = api.calls.filter((c) => c.path === '/api/compliance').length;
    await page.getByRole('button', { name: 'Reintentar' }).click();
    await expect.poll(() => api.calls.filter((c) => c.path === '/api/compliance').length).toBe(antes + 1);
  });

  test('la gestión de hallazgos remite a los hallazgos en vivo', async ({ page }) => {
    await abrir(page, 'secops/gestion', 'Seguridad');
    await expect(page.getByRole('alert')).toContainText('Los hallazgos en vivo siguen en la otra pestaña');
  });
});

test.describe('sin conexión con Azure', () => {
  test.use({ overrides: { 'GET /api/inventory/health': () => ({ azureConnected: false }) } });

  test('el indicador lo dice', async ({ page }) => {
    await abrir(page, 'resumen', 'Resumen');
    await expect(page.getByText('Sin conexión')).toBeVisible();
  });
});

test.describe('error al guardar', () => {
  test.use({
    role: 'operador',
    overrides: { 'POST /api/compliance/assets/classification': () => new Respuesta(500, { detail: 'La base no respondió a tiempo.' }) },
    allowedConsoleErrors: [/500/],
  });

  test('el panel muestra el error y conserva el formulario', async ({ page }) => {
    await abrir(page, 'cumplimiento/activos', 'Cumplimiento');
    await page.getByRole('row', { name: /app-web-dev/ }).getByRole('button', { name: 'Detalle' }).click();
    const panel = page.getByRole('dialog');
    await panel.getByRole('button', { name: 'Cambiar clasificación' }).click();
    await panel.getByLabel(/^Motivo/).fill('Prueba de error');
    await panel.getByRole('button', { name: 'Guardar clasificación' }).click();
    await expect(panel.getByRole('alert')).toHaveText('La base no respondió a tiempo.');
    await expect(panel.getByLabel(/^Motivo/)).toHaveValue('Prueba de error');
  });
});

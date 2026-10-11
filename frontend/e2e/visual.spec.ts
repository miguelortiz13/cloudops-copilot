/**
 * Regresión visual (@visual): capturas de las vistas principales con datos
 * ficticios y reloj fijo. Solo se comparan dentro de la imagen de Playwright
 * (npm run test:e2e:docker); para aceptar un cambio de diseño intencional,
 * `npm run test:e2e:update` y revisar las capturas en el diff del PR.
 */
import type { Page } from '@playwright/test';
import { abrir, expect, test } from './mock-api';

async function estable(page: Page) {
  await page.waitForLoadState('networkidle');
  await expect(page.locator('[aria-busy="true"], .is-refreshing')).toHaveCount(0);
}

const VISTAS: [ruta: string, titulo: string, archivo: string][] = [
  ['resumen', 'Resumen', 'resumen'],
  ['inventario', 'Inventario', 'inventario'],
  ['finops/costos', 'Costos', 'costos-vision-general'],
  ['finops/historial', 'Costos', 'costos-historial'],
  ['secops/gestion', 'Seguridad', 'seguridad-gestion'],
  ['cumplimiento/controles', 'Cumplimiento', 'cumplimiento-controles'],
  ['cumplimiento/reglas', 'Cumplimiento', 'cumplimiento-reglas'],
  ['cumplimiento/activos', 'Cumplimiento', 'cumplimiento-activos'],
  ['admin/plataforma', 'Administración', 'admin-plataforma'],
];

test.describe('@visual', () => {
  for (const [ruta, titulo, archivo] of VISTAS) {
    test(`${archivo}`, async ({ page }) => {
      await abrir(page, ruta, titulo);
      await estable(page);
      await expect(page).toHaveScreenshot(`${archivo}.png`, { fullPage: true });
    });
  }

  test('detalle de un control', async ({ page }) => {
    await abrir(page, 'cumplimiento/controles', 'Cumplimiento');
    await estable(page);
    await page.getByRole('row', { name: /6\.2/ }).getByRole('button', { name: 'Detalle' }).click();
    await expect(page.getByRole('dialog')).toHaveScreenshot('cumplimiento-detalle-control.png');
  });

  test('cumplimiento en tema oscuro', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await abrir(page, 'cumplimiento/controles', 'Cumplimiento');
    await estable(page);
    await expect(page).toHaveScreenshot('cumplimiento-controles-oscuro.png', { fullPage: true });
  });

  test('cumplimiento en un teléfono', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await abrir(page, 'cumplimiento/activos', 'Cumplimiento');
    await estable(page);
    await expect(page).toHaveScreenshot('cumplimiento-activos-movil.png', { fullPage: true });
  });
});

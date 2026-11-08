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
  ['inicio/resumen', 'Resumen', 'resumen'],
  ['activos/inventario', 'Inventario', 'inventario'],
  ['activos/recursos/azure%3A%2Fsubscriptions%2F1%2Fx%2Fstdatos', 'stdatos', 'activos-ficha'],
  ['costos/gasto', 'Gasto', 'costos-vision-general'],
  ['costos/historial', 'Historial', 'costos-historial'],
  ['riesgo/hallazgos', 'Hallazgos', 'seguridad-gestion'],
  ['riesgo/cumplimiento', 'Cumplimiento', 'cumplimiento-controles'],
  ['riesgo/cumplimiento/reglas', 'Cumplimiento', 'cumplimiento-reglas'],
  ['riesgo/clasificacion', 'Clasificación de activos', 'cumplimiento-activos'],
  ['activos/kubernetes', 'Kubernetes', 'kubernetes'],
  ['operacion/incidentes', 'Incidentes', 'incidentes'],
  ['plataforma/reportes', 'Reportes y automatización', 'reportes'],
  ['plataforma/estado', 'Estado de la plataforma', 'admin-plataforma'],
  ['plataforma/cuentas', 'Cuentas', 'admin-cuentas'],
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
    await abrir(page, 'riesgo/cumplimiento', 'Cumplimiento');
    await estable(page);
    await page.getByRole('row', { name: /6\.2/ }).getByRole('button', { name: 'Detalle' }).click();
    await expect(page.getByRole('dialog')).toHaveScreenshot('cumplimiento-detalle-control.png');
  });

  test('cumplimiento en tema oscuro', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await abrir(page, 'riesgo/cumplimiento', 'Cumplimiento');
    await estable(page);
    await expect(page).toHaveScreenshot('cumplimiento-controles-oscuro.png', { fullPage: true });
  });

  test('cumplimiento en un teléfono', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await abrir(page, 'riesgo/clasificacion', 'Clasificación de activos');
    await estable(page);
    await expect(page).toHaveScreenshot('cumplimiento-activos-movil.png', { fullPage: true });
  });
});

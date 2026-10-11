import { abrir, expect, test } from './mock-api';

test.use({ viewport: { width: 390, height: 844 } });

for (const ruta of ['resumen', 'cumplimiento/controles', 'cumplimiento/activos', 'secops/gestion']) {
  test(`#/${ruta} no tiene scroll horizontal en un teléfono`, async ({ page }) => {
    await abrir(page, ruta, /.+/);
    await page.waitForLoadState('networkidle');
    const desborde = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(desborde).toBeLessThanOrEqual(0);
  });
}

test('el menú abre la navegación y la cierra al elegir', async ({ page }) => {
  await abrir(page, 'resumen', 'Resumen');
  await page.getByRole('button', { name: 'Menú' }).click();
  const nav = page.getByRole('navigation', { name: 'Secciones' });
  await nav.getByText('Cumplimiento').click();
  await expect(page.getByRole('heading', { level: 1, name: 'Cumplimiento' })).toBeVisible();
  await expect(page.locator('.overlay')).toHaveCount(0);
});

test('la ruta de navegación no se monta sobre las acciones de la barra', async ({ page }) => {
  await abrir(page, 'cumplimiento/activos', 'Cumplimiento');
  await expect(page.getByText('Conectado')).toBeVisible();
  // Se mide lo que se ve (cada texto de la ruta, también lo que desborda), no
  // la caja del contenedor, que se encoge.
  const acciones = (await page.locator('.topbar-actions').boundingBox())!;
  const textos = await page.locator('.breadcrumb').evaluate((el) =>
    [...el.querySelectorAll('span, strong')]
      .filter((n) => getComputedStyle(n).display !== 'none' && n.getClientRects().length)
      .map((n) => { const r = n.getBoundingClientRect(); return { derecha: r.right, alto: r.height }; }));
  expect(Math.max(...textos.map((t) => t.derecha))).toBeLessThanOrEqual(acciones.x);
  expect(Math.max(...textos.map((t) => t.alto)), 'la ruta ocupa una sola línea').toBeLessThan(24);
  await expect(page.locator('.breadcrumb')).toContainText('Clasificación de activos');
});

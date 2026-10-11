import { abrir, expect, test } from './mock-api';

/** Cada sección y subvista del panel, con el título que debe mostrar. */
const SECCIONES: [ruta: string, titulo: string, migas: string][] = [
  ['resumen', 'Resumen', 'Resumen'],
  ['inventario', 'Inventario', 'Inventario'],
  ['finops/costos', 'Costos', 'Visión general'],
  ['finops/historial', 'Costos', 'Historial y comparación'],
  ['finops/ahorro', 'Costos', 'Optimización y ahorro'],
  ['secops/vivo', 'Seguridad', 'Seguridad'],
  ['secops/gestion', 'Seguridad', 'Gestión de hallazgos'],
  ['iac', 'Infraestructura como código', 'IaC y Terraform'],
  ['cumplimiento/controles', 'Cumplimiento', 'Controles'],
  ['cumplimiento/reglas', 'Cumplimiento', 'Catálogo de reglas'],
  ['cumplimiento/activos', 'Cumplimiento', 'Clasificación de activos'],
  ['reportes', 'Reportes y automatización', 'Reportes'],
  ['admin/actividad', 'Administración', 'Actividad de usuarios'],
  ['admin/plataforma', 'Administración', 'Base y recolectores'],
];

for (const [ruta, titulo, migas] of SECCIONES) {
  test(`#/${ruta} carga sin errores`, async ({ page, api }) => {
    await abrir(page, ruta, titulo);
    await expect(page.getByRole('navigation', { name: 'Secciones' })).toBeVisible();
    await expect(page.locator('.breadcrumb')).toContainText(migas);
    // Ni el aviso de sección caída ni un estado de error.
    await expect(page.getByText(/No se pudo mostrar la sección|No se pudo cargar/)).toHaveCount(0);
    await page.waitForLoadState('networkidle');
    expect(api.calls.length).toBeGreaterThan(0);
  });
}

test('la barra lateral navega y marca la sección activa', async ({ page }) => {
  await abrir(page, 'resumen', 'Resumen');
  const nav = page.getByRole('navigation', { name: 'Secciones' });
  await nav.getByRole('button', { name: 'Cumplimiento' }).or(nav.getByRole('link', { name: 'Cumplimiento' })).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Cumplimiento' })).toBeVisible();
  await expect(page).toHaveURL(/#\/cumplimiento/);
  await expect(page).toHaveTitle('Cumplimiento · CloudOps Copilot');
});

test('el enlace anterior #iso abre Cumplimiento', async ({ page }) => {
  await page.goto('/#/iso');
  await expect(page.getByRole('heading', { level: 1, name: 'Cumplimiento' })).toBeVisible();
});

test('una ruta desconocida vuelve al resumen', async ({ page }) => {
  await page.goto('/#/no-existe');
  await expect(page.getByRole('heading', { level: 1, name: 'Resumen' })).toBeVisible();
});

test('el tema oscuro se aplica y se recuerda', async ({ page }) => {
  await abrir(page, 'resumen', 'Resumen');
  const html = page.locator('html');
  for (let i = 0; i < 3 && (await html.getAttribute('data-theme')) !== 'dark'; i++) {
    await page.getByRole('button', { name: 'Cambiar tema' }).click();
  }
  await expect(html).toHaveAttribute('data-theme', 'dark');
  await page.reload();
  await expect(html).toHaveAttribute('data-theme', 'dark');
});

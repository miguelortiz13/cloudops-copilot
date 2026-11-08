import { abrir, expect, test } from './mock-api';

/** Cada sección y subvista del panel, con el título que debe mostrar. */
const SECCIONES: [ruta: string, titulo: string, migas: string][] = [
  ['inicio/resumen', 'Resumen', 'Inicio'],
  ['activos/inventario', 'Inventario', 'Activos'],
  ['activos/iac', 'Infraestructura como código', 'IaC y Terraform'],
  ['activos/kubernetes', 'Kubernetes', 'Activos'],
  ['costos/gasto', 'Gasto', 'Costos'],
  ['costos/historial', 'Historial', 'Costos'],
  ['costos/ahorro', 'Ahorro', 'Costos'],
  ['riesgo/hallazgos', 'Hallazgos', 'Riesgo'],
  ['riesgo/exposicion', 'Exposición en vivo', 'Riesgo'],
  ['riesgo/cumplimiento', 'Cumplimiento', 'Riesgo'],
  ['riesgo/cumplimiento/reglas', 'Cumplimiento', 'Riesgo'],
  ['riesgo/clasificacion', 'Clasificación de activos', 'Clasificación'],
  ['operacion/incidentes', 'Incidentes', 'Operación'],
  ['operacion/silencios', 'Silencios', 'Operación'],
  ['operacion/avisos', 'Avisos', 'Operación'],
  ['plataforma/reportes', 'Reportes y automatización', 'Plataforma'],
  ['plataforma/ajustes', 'Ajustes', 'Plataforma'],
  ['plataforma/cuentas', 'Cuentas', 'Plataforma'],
  ['plataforma/auditoria', 'Auditoría', 'Plataforma'],
  ['plataforma/estado', 'Estado de la plataforma', 'Plataforma'],
];

/** Rutas anteriores a los dominios (enlaces guardados y avisos ya enviados) → su sección nueva. */
const ANTERIORES: [ruta: string, nueva: string, titulo: string][] = [
  ['resumen', 'inicio/resumen', 'Resumen'],
  ['finops/historial', 'costos/historial', 'Historial'],
  ['secops/gestion', 'riesgo/hallazgos', 'Hallazgos'],
  ['cumplimiento/activos', 'riesgo/clasificacion', 'Clasificación de activos'],
  ['kubernetes/homelab', 'activos/kubernetes/homelab', 'Kubernetes'],
  ['incidentes/2', 'operacion/incidentes/2', 'Incidentes'],
  ['admin/plataforma', 'plataforma/estado', 'Estado de la plataforma'],
];

for (const [ruta, nueva, titulo] of ANTERIORES) {
  test(`#/${ruta} redirige a #/${nueva}`, async ({ page }) => {
    await abrir(page, ruta, titulo);
    await expect(page).toHaveURL(new RegExp(`#/${nueva}$`));
  });
}

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
  await abrir(page, 'inicio/resumen', 'Resumen');
  const nav = page.getByRole('navigation', { name: 'Secciones' });
  await nav.getByRole('link', { name: 'Cumplimiento' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Cumplimiento' })).toBeVisible();
  await expect(page).toHaveURL(/#\/riesgo\/cumplimiento/);
  await expect(nav.getByRole('link', { name: 'Cumplimiento' })).toHaveAttribute('aria-current', 'page');
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
  await abrir(page, 'inicio/resumen', 'Resumen');
  const html = page.locator('html');
  for (let i = 0; i < 3 && (await html.getAttribute('data-theme')) !== 'dark'; i++) {
    await page.getByRole('button', { name: 'Cambiar tema' }).click();
  }
  await expect(html).toHaveAttribute('data-theme', 'dark');
  await page.reload();
  await expect(html).toHaveAttribute('data-theme', 'dark');
});

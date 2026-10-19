import { abrir, expect, test } from './mock-api';

test('el filtro por nube deja solo AWS en las vistas de la base y avisa en las de Azure en vivo', async ({ page }) => {
  await abrir(page, 'secops/gestion', 'Seguridad');
  await page.getByRole('button', { name: /Todas las cuentas \(3\)/ }).click();
  await page.getByRole('checkbox', { name: 'Microsoft Azure' }).click();
  await expect(page.getByRole('button', { name: /AWS laboratorio \(demo\)/ })).toBeVisible();
  // Los hallazgos de prueba son de Azure: con solo AWS la bandeja queda vacía.
  await expect(page.getByRole('radio', { name: /Activos \(0\)/ })).toBeVisible();

  // Navegar dentro del panel conserva el filtro (recargar lo reinicia).
  await page.getByRole('link', { name: 'Inventario', exact: true }).click();
  await expect(page.getByText('no incluye ninguna suscripción de Azure')).toBeVisible();

  await page.getByRole('link', { name: 'Reportes', exact: true }).click();
  await expect(page.getByText('AWS laboratorio (demo)')).toBeVisible();
  await expect(page.getByText('Producción (demo)')).toHaveCount(0);
});

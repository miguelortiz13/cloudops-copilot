import { abrir, expect, test } from './mock-api';

test('el incidente muestra el diagnóstico con sus citas y se puede marcar como correcto', async ({ page, api }) => {
  await abrir(page, 'incidentes', 'Incidentes');
  await expect(page.getByText('no alcanza su base', { exact: false })).toBeVisible();
  await expect(page.getByRole('link', { name: 'ver' }).first()).toHaveAttribute('href', '#/kubernetes/local-k8s-lab');
  await expect(page.getByText('Consultó: estado_cluster, recursos_nuevos')).toBeVisible();
  await page.getByRole('button', { name: 'Correcto', exact: true }).click();
  await expect.poll(() => api.lastBody('POST /api/incidents/2/feedback')).toEqual({ value: 'correcto' });
});

test.describe('lector', () => {
  test.use({ role: 'lector' });
  test('no puede marcar el diagnóstico', async ({ page }) => {
    await abrir(page, 'incidentes', 'Incidentes');
    await expect(page.getByText('no alcanza su base', { exact: false })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Correcto', exact: true })).toHaveCount(0);
  });
});

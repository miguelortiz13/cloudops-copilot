import { abrir, expect, test } from './mock-api';

test('la página de Kubernetes muestra el clúster y avisa del que no reporta', async ({ page }) => {
  await abrir(page, 'kubernetes', 'Kubernetes');
  await expect(page.getByText('CrashLoopBackOff: grafana-7d9c6b5f4-x2kqp')).toBeVisible();

  await page.getByRole('tab', { name: 'aks-lab' }).click();
  await expect(page).toHaveURL(/#\/kubernetes\/aks-lab/);
  await expect(page.getByText('El agente de aks-lab todavía no envió ninguna foto', { exact: false })).toBeVisible();
});

test.describe('sin clústeres', () => {
  test.use({ overrides: { 'GET /api/k8s/clusters': () => ({ clusters: [] }) } });
  test('muestra la guía para conectar el primero', async ({ page }) => {
    await abrir(page, 'kubernetes', 'Kubernetes');
    await expect(page.getByText('Todavía no hay clústeres conectados')).toBeVisible();
    await expect(page.getByText('kubectl apply -k k8s-agent/')).toBeVisible();
  });
});

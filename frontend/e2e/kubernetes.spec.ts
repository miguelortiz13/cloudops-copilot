import { abrir, expect, test } from './mock-api';

test('la página de Kubernetes muestra el clúster y avisa del que no reporta', async ({ page }) => {
  await abrir(page, 'activos/kubernetes', 'Kubernetes');
  await expect(page.getByText('CrashLoopBackOff: grafana-7d9c6b5f4-x2kqp')).toBeVisible();

  await page.getByRole('button', { name: 'Ver log' }).click();
  await expect(page.getByText('failed to initialize database', { exact: false })).toBeVisible();
  await page.keyboard.press('Escape');

  await expect(page.getByText('Sin soporte desde el', { exact: false })).toBeVisible();
  await expect(page.getByText('Parche 1.31.14 disponible')).toBeVisible();
  await page.getByRole('button', { name: 'aks-lab' }).click();
  await expect(page).toHaveURL(/#\/activos\/kubernetes\/aks-lab/);
  await expect(page.getByText('El agente de aks-lab todavía no envió ninguna foto', { exact: false })).toBeVisible();
});

test('un operador abre un incidente desde una incidencia y ajusta el clúster', async ({ page, api }) => {
  await abrir(page, 'activos/kubernetes', 'Kubernetes');
  await expect(page.getByText('Silenciada hasta el', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Abrir incidente' }).first().click();
  await expect.poll(() => api.lastBody('POST /api/k8s/clusters/homelab/incidents'))
    .toEqual({ resource: 'pod/grafana-7d9c6b5f4-x2kqp', namespace: 'monitoring' });
  await expect(page).toHaveURL(/#\/operacion\/incidentes\/3/);

  await abrir(page, 'activos/kubernetes', 'Kubernetes');
  await page.getByLabel('Namespaces ignorados').fill('pruebas, demo');
  await page.getByRole('button', { name: 'Guardar' }).click();
  await expect.poll(() => api.lastBody('PUT /api/settings/k8s/homelab'))
    .toEqual({ namespaces_ignorados: ['pruebas', 'demo'], reinicios: 5, gracia_min: 10, avisar: true, avisar_severidades: ['critica', 'alta'] });
});

test.describe('sin clústeres', () => {
  test.use({ overrides: { 'GET /api/k8s/clusters': () => ({ clusters: [] }) } });
  test('muestra la guía para conectar el primero', async ({ page }) => {
    await abrir(page, 'activos/kubernetes', 'Kubernetes');
    await expect(page.getByText('Todavía no hay clústeres conectados')).toBeVisible();
    await expect(page.getByText('kubectl apply -k k8s-agent/')).toBeVisible();
  });
});

import { abrir, expect, test } from './mock-api';

test.use({ role: 'operador' });

test('aceptar un riesgo con vencimiento y justificación', async ({ page, api }) => {
  await abrir(page, 'secops/gestion', 'Seguridad');
  await page.getByRole('row', { name: /kv-pagos-prod/ }).getByRole('button', { name: 'Gestionar' }).click();
  const panel = page.getByRole('dialog', { name: 'Key Vault alcanzable desde red pública' });
  await expect(panel.getByText('CIS 8.7')).toBeVisible();
  await expect(panel.getByText('Detectado por el recolector')).toBeVisible();

  await panel.getByRole('button', { name: 'Aceptar el riesgo' }).click();
  const confirmar = panel.getByRole('button', { name: 'Aceptar el riesgo' });
  await expect(confirmar).toBeDisabled();
  // No se puede elegir una fecha pasada: el mínimo es mañana.
  await expect(panel.getByLabel(/^Vence el/)).toHaveAttribute('min', '2026-10-11');
  await panel.getByLabel(/^Vence el/).fill('2027-01-31');
  await panel.getByLabel(/^Justificación/).fill('Mitigado por el firewall de aplicación');
  await confirmar.click();

  await expect(page.locator('.toast')).toHaveText('Estado actualizado: Riesgo aceptado.');
  expect(api.lastBody('POST /api/findings/2/status')).toEqual({
    status: 'aceptado', note: 'Mitigado por el firewall de aplicación', accepted_until: '2027-01-31',
  });
  await panel.getByRole('button', { name: 'Cerrar' }).click();
  await page.getByRole('radio', { name: /Aceptados/ }).click();
  await expect(page.getByRole('row', { name: /kv-pagos-prod/ })).toContainText('hasta el 31 de ene de 2027');
});

test('asumir un hallazgo deja al usuario como responsable', async ({ page }) => {
  await abrir(page, 'secops/gestion', 'Seguridad');
  await page.getByRole('row', { name: /nsg-pagos-prod/ }).getByRole('button', { name: 'Gestionar' }).click();
  const panel = page.getByRole('dialog');
  await panel.getByRole('button', { name: 'Asumir' }).click();
  await panel.getByRole('button', { name: 'Asumir' }).click();
  await expect(page.locator('.toast')).toHaveText('Estado actualizado: Asumido.');
  await expect(panel.getByText('ana@contoso.example')).toBeVisible();
});

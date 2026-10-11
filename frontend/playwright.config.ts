import { defineConfig, devices } from '@playwright/test';

/**
 * Pruebas E2E del panel contra el build de producción, con el API simulado
 * (e2e/mock-api.ts): no necesitan backend, Azure ni credenciales.
 *
 * Las capturas de regresión visual (@visual) se generan y comparan dentro de
 * la imagen oficial de Playwright (npm run test:e2e:docker), la misma que usa
 * la CI: fuera de ella el renderizado de fuentes cambia y darían falsos fallos.
 */
import { API_URL } from './e2e/mock-api';
const PORT = 4173;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list']],
  snapshotPathTemplate: '{testDir}/__screenshots__/{testFileName}/{arg}{ext}',
  expect: {
    // Dentro de la imagen de Playwright el renderizado es determinista: un
    // umbral relativo (0,2 %) dejaba pasar cambios de texto visibles.
    toHaveScreenshot: { animations: 'disabled', caret: 'hide', maxDiffPixels: 20 },
  },
  use: {
    baseURL: `http://localhost:${PORT}`,
    locale: 'es-CO',
    timezoneId: 'America/Bogota',
    colorScheme: 'light',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
  webServer: {
    command: `npx vite build --outDir dist-e2e --emptyOutDir && npx vite preview --outDir dist-e2e --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    // Siempre un build nuevo: reutilizar un servidor viejo probaría código anterior.
    reuseExistingServer: false,
    timeout: 180_000,
    env: { VITE_API_URL: API_URL, VITE_AZURE_AD_CLIENT_ID: '', VITE_USER_DISPLAY_NAME: 'Ana Prueba' },
  },
});

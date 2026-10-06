/**
 * Autenticación con Microsoft Entra ID para el panel.
 *
 * El backend valida un bearer token cuando corre con `AUTH_ENABLED=true`. Este
 * módulo obtiene ese token con MSAL y lo adjunta a cada llamada del panel.
 *
 * Queda inactivo mientras no se defina `VITE_AZURE_AD_CLIENT_ID` en tiempo de
 * compilación, de modo que el desarrollo local y el despliegue actual siguen
 * funcionando sin cambios hasta que se registre la aplicación en Entra ID.
 *
 * Para activarlo, crear un archivo `.env.production` en `frontend/` con:
 *
 *     VITE_AZURE_AD_CLIENT_ID=<client id del App Registration del panel>
 *     VITE_AZURE_AD_TENANT_ID=<tenant id>
 *     VITE_API_SCOPE=api://<client id del API>/access_as_user
 */

// MSAL se importa de forma dinamica para que Vite lo deje en un chunk aparte:
// pesa ~250 kB y no debe viajar en el bundle principal cuando la autenticacion
// esta desactivada, que es el valor por defecto. El import de tipos se borra en
// tiempo de compilacion y no arrastra codigo.
import type {
  PublicClientApplication,
  AccountInfo,
} from '@azure/msal-browser';

const CLIENT_ID = import.meta.env.VITE_AZURE_AD_CLIENT_ID as string | undefined;
const TENANT_ID = import.meta.env.VITE_AZURE_AD_TENANT_ID as string | undefined;
const API_SCOPE = import.meta.env.VITE_API_SCOPE as string | undefined;

/** Indica si el panel debe exigir inicio de sesión. */
export const authEnabled = Boolean(CLIENT_ID && TENANT_ID && API_SCOPE);

let msalInstance: PublicClientApplication | null = null;

/**
 * Devuelve la instancia de MSAL, cargando la librería y ejecutando su
 * inicialización la primera vez. Todas las funciones del módulo pasan por aquí,
 * así que no hay forma de usar una instancia sin inicializar.
 */
async function getInstance(): Promise<PublicClientApplication> {
  if (!msalInstance) {
    const msal = await import('@azure/msal-browser');
    msalInstance = new msal.PublicClientApplication({
      auth: {
        clientId: CLIENT_ID as string,
        authority: `https://login.microsoftonline.com/${TENANT_ID}`,
        // Con barra final: es la forma que Entra ID acepta como redirect URI.
        redirectUri: `${window.location.origin}/`,
      },
      cache: {
        // sessionStorage mantiene la sesión acotada a la pestaña, que es lo
        // adecuado para un panel con datos de infraestructura.
        cacheLocation: 'sessionStorage',
      },
    });
    await msalInstance.initialize();
  }
  return msalInstance;
}

/**
 * Prepara MSAL y resuelve una redirección de login pendiente.
 * Devuelve la cuenta activa, o null si todavía no hay sesión.
 */
export async function initAuth(): Promise<AccountInfo | null> {
  if (!authEnabled) return null;

  const instance = await getInstance();

  const redirectResult = await instance.handleRedirectPromise();
  if (redirectResult?.account) {
    instance.setActiveAccount(redirectResult.account);
    return redirectResult.account;
  }

  const accounts = instance.getAllAccounts();
  if (accounts.length > 0) {
    instance.setActiveAccount(accounts[0]);
    return accounts[0];
  }
  return null;
}

/** Inicia el flujo de login por redirección. */
export async function login(): Promise<void> {
  if (!authEnabled) return;
  const instance = await getInstance();
  await instance.loginRedirect({ scopes: [API_SCOPE as string] });
}

/** Cierra la sesión del panel. */
export async function logout(): Promise<void> {
  if (!authEnabled) return;
  const instance = await getInstance();
  await instance.logoutRedirect();
}

/**
 * Token de acceso vigente para el API.
 *
 * Intenta primero en silencio; si Entra ID pide interacción (consentimiento o
 * sesión expirada) escala a redirección. Devuelve null cuando la autenticación
 * está desactivada, y en ese caso las peticiones salen sin cabecera.
 */
export async function getAccessToken(): Promise<string | null> {
  if (!authEnabled) return null;

  const instance = await getInstance();

  const account = instance.getActiveAccount() ?? instance.getAllAccounts()[0];
  if (!account) return null;

  try {
    const result = await instance.acquireTokenSilent({
      scopes: [API_SCOPE as string],
      account,
    });
    return result.accessToken;
  } catch (error) {
    if ((error as { name?: string })?.name === 'InteractionRequiredAuthError') {
      await instance.acquireTokenRedirect({ scopes: [API_SCOPE as string] });
      return null;
    }
    console.error('No se pudo obtener el token de acceso:', error);
    return null;
  }
}

/**
 * `fetch` con el bearer token del panel ya adjunto.
 *
 * Se usa en lugar de `fetch` en todas las llamadas al API para que activar la
 * autenticación no obligue a tocar cada punto de llamada.
 */
export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const token = await getAccessToken();
  if (!token) return fetch(input, init);

  const headers = new Headers(init.headers || {});
  headers.set('Authorization', `Bearer ${token}`);
  return fetch(input, { ...init, headers });
}

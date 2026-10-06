/** Configuración de compilación del panel (variables VITE_*). */

export const API_URL =
  (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') || 'http://localhost:8000';

export const USER_NAME = (import.meta.env.VITE_USER_DISPLAY_NAME as string | undefined) || 'Operador';
export const USER_ROLE = (import.meta.env.VITE_USER_ROLE as string | undefined) || 'DevOps Engineer';
export const USER_INITIALS = USER_NAME.split(/\s+/)
  .map((p) => p[0])
  .join('')
  .slice(0, 2)
  .toUpperCase();

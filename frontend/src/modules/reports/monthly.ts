/** Reporte mensual por bloques (fase 5 del plan 10). */

export const BLOQUES = [
  { id: 'costos', label: 'Costos' }, { id: 'seguridad', label: 'Seguridad' }, { id: 'inventario', label: 'Inventario' },
  { id: 'incidentes', label: 'Incidentes' }, { id: 'plataforma', label: 'Plataforma' },
];

/** La URL del PDF con los bloques elegidos (todos = sin filtro) y la narración de la IA. */
export function monthlyUrl(month: string, bloques: string[], narrar: boolean): string {
  const q = new URLSearchParams({ month });
  if (bloques.length < BLOQUES.length) q.set('bloques', bloques.join(','));
  if (narrar) q.set('narrar', 'true');
  return `/api/reports/monthly?${q}`;
}

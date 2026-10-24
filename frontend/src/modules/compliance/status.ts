import type { ControlStatus } from '../../lib/types';

export const CONTROL_STATUS: Record<ControlStatus, { label: string; dot?: string; hint: string }> = {
  no_cumple: { label: 'No cumple', dot: 'dot-critical', hint: 'Hay hallazgos abiertos o asumidos' },
  sin_evidencia: { label: 'Sin evidencia', hint: 'La regla no se pudo evaluar en la última recolección' },
  riesgo_aceptado: { label: 'Riesgo aceptado', dot: 'dot-warning', hint: 'Solo quedan riesgos aceptados con vencimiento' },
  cumple: { label: 'Cumple', dot: 'dot-good', hint: 'Evaluado y sin hallazgos activos' },
};

/** Nombre corto del marco para las etiquetas de control ("CIS 6.1"). */
export const SHORT: Record<string, string> = {
  'cis-azure-2.0.0': 'CIS', 'cis-aws-3.0.0': 'CIS AWS', 'cis-kubernetes-1.9.0': 'CIS K8s', 'iso-27001-2022': 'ISO',
};

/** Nombre del marco en el selector: "CIS Azure 2.0.0", "CIS Kubernetes 1.9.0", "ISO 27001:2022". */
export function frameworkLabel(f: { id: string; version: string }): string {
  if (f.id === 'iso-27001-2022') return 'ISO 27001:2022';
  const nombre = { 'cis-azure-2.0.0': 'CIS Azure', 'cis-aws-3.0.0': 'CIS AWS', 'cis-kubernetes-1.9.0': 'CIS Kubernetes' }[f.id];
  return `${nombre ?? SHORT[f.id] ?? f.id} ${f.version}`;
}

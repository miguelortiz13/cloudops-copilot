import type { ReactNode } from 'react';
import type { Role } from '../lib/types';
import {
  Activity, BellOff, BellRing, Boxes, GitCompareArrows, Layers, Megaphone, CircleDollarSign, ClipboardCheck, Container, FileCode2, FileSpreadsheet, History, LayoutGrid,
  Plug, PiggyBank, Radar, ScrollText, Settings2, ShieldCheck, Siren, Tags,
} from 'lucide-react';

/**
 * Los 6 dominios de la plataforma (docs/plan/10-reestructuracion-por-dominios.md), en el orden de la
 * barra lateral, con sus secciones. Una sección vive en `#/<dominio>/<sección>[/<detalle>]`.
 * `role`: solo se muestra a quien tenga al menos ese rol (el API también lo exige).
 */
export const NAV: { group: string; id: string; items: { id: string; label: string; icon: ReactNode; role?: Role }[] }[] = [
  {
    group: 'Inicio', id: 'inicio',
    items: [{ id: 'inicio/resumen', label: 'Resumen', icon: <LayoutGrid size={16} /> }],
  },
  {
    group: 'Activos', id: 'activos',
    items: [
      { id: 'activos/recursos', label: 'Recursos', icon: <Layers size={16} /> },
      { id: 'activos/inventario', label: 'Inventario Azure', icon: <Boxes size={16} /> },
      { id: 'activos/iac', label: 'IaC y Terraform', icon: <FileCode2 size={16} /> },
      { id: 'activos/drift', label: 'Drift de Terraform', icon: <GitCompareArrows size={16} /> },
      { id: 'activos/kubernetes', label: 'Kubernetes', icon: <Container size={16} /> },
    ],
  },
  {
    group: 'Costos', id: 'costos',
    items: [
      { id: 'costos/gasto', label: 'Gasto', icon: <CircleDollarSign size={16} /> },
      { id: 'costos/historial', label: 'Historial', icon: <History size={16} /> },
      { id: 'costos/ahorro', label: 'Ahorro', icon: <PiggyBank size={16} /> },
      { id: 'costos/alertas', label: 'Alertas de costo', icon: <BellRing size={16} /> },
    ],
  },
  {
    group: 'Riesgo', id: 'riesgo',
    items: [
      { id: 'riesgo/hallazgos', label: 'Hallazgos', icon: <ClipboardCheck size={16} /> },
      { id: 'riesgo/exposicion', label: 'Exposición en vivo', icon: <Radar size={16} /> },
      { id: 'riesgo/cumplimiento', label: 'Cumplimiento', icon: <ShieldCheck size={16} /> },
      { id: 'riesgo/clasificacion', label: 'Clasificación', icon: <Tags size={16} /> },
    ],
  },
  {
    group: 'Operación', id: 'operacion',
    items: [
      { id: 'operacion/incidentes', label: 'Incidentes', icon: <Siren size={16} /> },
      { id: 'operacion/silencios', label: 'Silencios', icon: <BellOff size={16} /> },
      { id: 'operacion/avisos', label: 'Avisos', icon: <Megaphone size={16} /> },
    ],
  },
  {
    group: 'Plataforma', id: 'plataforma',
    items: [
      { id: 'plataforma/reportes', label: 'Reportes', icon: <FileSpreadsheet size={16} /> },
      { id: 'plataforma/ajustes', label: 'Ajustes', icon: <Settings2 size={16} /> },
      { id: 'plataforma/cuentas', label: 'Cuentas', icon: <Plug size={16} />, role: 'administrador' },
      { id: 'plataforma/auditoria', label: 'Auditoría', icon: <ScrollText size={16} />, role: 'administrador' },
      { id: 'plataforma/estado', label: 'Estado', icon: <Activity size={16} />, role: 'administrador' },
    ],
  },
];

const SECCIONES = new Set(NAV.flatMap((g) => g.items.map((i) => i.id)));

/**
 * Rutas anteriores a los dominios (enlaces guardados, avisos ya enviados, documentación) → su sección
 * nueva. shortcut: se retiran en la fase 6 del plan, cuando lleven 30 días sin uso.
 */
const ANTERIORES: Record<string, string> = {
  resumen: 'inicio/resumen', inventario: 'activos/inventario', iac: 'activos/iac', kubernetes: 'activos/kubernetes',
  finops: 'costos/gasto', 'finops/costos': 'costos/gasto', 'finops/historial': 'costos/historial', 'finops/ahorro': 'costos/ahorro',
  secops: 'riesgo/exposicion', 'secops/vivo': 'riesgo/exposicion', 'secops/gestion': 'riesgo/hallazgos',
  cumplimiento: 'riesgo/cumplimiento', 'cumplimiento/controles': 'riesgo/cumplimiento',
  'cumplimiento/reglas': 'riesgo/cumplimiento/reglas', 'cumplimiento/activos': 'riesgo/clasificacion',
  iso: 'riesgo/cumplimiento', incidentes: 'operacion/incidentes', reportes: 'plataforma/reportes',
  admin: 'plataforma/auditoria', 'admin/actividad': 'plataforma/auditoria', 'admin/cuentas': 'plataforma/cuentas',
  'admin/plataforma': 'plataforma/estado',
};

/**
 * La sección de una ruta y lo que sigue (un clúster, un incidente, una vista interna), o la ruta nueva a la
 * que hay que redirigir. Un dominio solo lleva a su primera sección; lo desconocido, al resumen.
 */
export function resolver(partes: string[]): { seccion: string; resto: string[] } | { redirigir: string } {
  const [a = '', b = '', ...resto] = partes;
  if (SECCIONES.has(`${a}/${b}`)) return { seccion: `${a}/${b}`, resto };
  const dominio = NAV.find((g) => g.id === a);
  if (dominio && !b) return { redirigir: dominio.items[0].id };
  const anterior = ANTERIORES[`${a}/${b}`] ?? ANTERIORES[a];
  if (anterior) {
    // Lo que seguía a la ruta vieja se conserva: #/kubernetes/lab → #/activos/kubernetes/lab.
    const sobra = ANTERIORES[`${a}/${b}`] ? resto : [b, ...resto].filter(Boolean);
    return { redirigir: [anterior, ...sobra].join('/') };
  }
  return { redirigir: 'inicio/resumen' };
}

export const ETIQUETA: Record<string, { dominio: string; seccion: string }> = Object.fromEntries(
  NAV.flatMap((g) => g.items.map((i) => [i.id, { dominio: g.group, seccion: i.label }])),
);

import type { ReactNode } from 'react';
import {
  Boxes, CircleDollarSign, FileCode2, FileSpreadsheet, LayoutGrid, ShieldCheck, ShieldHalf,
} from 'lucide-react';

/** Secciones de la plataforma, en el orden de la barra lateral. */
export const NAV: { group: string; items: { id: string; label: string; icon: ReactNode }[] }[] = [
  {
    group: 'General',
    items: [{ id: 'resumen', label: 'Resumen', icon: <LayoutGrid size={16} /> }],
  },
  {
    group: 'Operación',
    items: [
      { id: 'inventario', label: 'Inventario', icon: <Boxes size={16} /> },
      { id: 'finops', label: 'Costos', icon: <CircleDollarSign size={16} /> },
      { id: 'secops', label: 'Seguridad', icon: <ShieldHalf size={16} /> },
      { id: 'iac', label: 'IaC y Terraform', icon: <FileCode2 size={16} /> },
      { id: 'iso', label: 'ISO 27001', icon: <ShieldCheck size={16} /> },
    ],
  },
  {
    group: 'Herramientas',
    items: [{ id: 'reportes', label: 'Reportes', icon: <FileSpreadsheet size={16} /> }],
  },
];

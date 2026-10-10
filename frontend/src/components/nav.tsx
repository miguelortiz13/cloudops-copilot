import type { ReactNode } from 'react';
import type { Role } from '../lib/types';
import {
  Boxes, CircleDollarSign, FileCode2, FileSpreadsheet, LayoutGrid, Settings2, ShieldCheck, ShieldHalf,
} from 'lucide-react';

/** Secciones de la plataforma, en el orden de la barra lateral. */
/** `role`: solo se muestra a quien tenga al menos ese rol (el API también lo exige). */
export const NAV: { group: string; items: { id: string; label: string; icon: ReactNode; role?: Role }[] }[] = [
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
      { id: 'cumplimiento', label: 'Cumplimiento', icon: <ShieldCheck size={16} /> },
    ],
  },
  {
    group: 'Herramientas',
    items: [
      { id: 'reportes', label: 'Reportes', icon: <FileSpreadsheet size={16} /> },
      { id: 'admin', label: 'Administración', icon: <Settings2 size={16} />, role: 'administrador' },
    ],
  },
];

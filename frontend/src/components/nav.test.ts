import { describe, expect, it } from 'vitest';
import { resolver } from './nav';

const ruta = (hash: string) => resolver(hash.split('/').filter(Boolean));

describe('navegación por dominios', () => {
  it('una sección se resuelve con lo que le sigue', () => {
    expect(ruta('activos/kubernetes/lab')).toEqual({ seccion: 'activos/kubernetes', resto: ['lab'] });
    expect(ruta('riesgo/cumplimiento/reglas')).toEqual({ seccion: 'riesgo/cumplimiento', resto: ['reglas'] });
  });

  it('las rutas anteriores redirigen a su sección y conservan el detalle', () => {
    expect(ruta('')).toEqual({ redirigir: 'inicio/resumen' });
    expect(ruta('kubernetes/lab')).toEqual({ redirigir: 'activos/kubernetes/lab' });
    expect(ruta('incidentes/12')).toEqual({ redirigir: 'operacion/incidentes/12' });
    expect(ruta('secops/gestion')).toEqual({ redirigir: 'riesgo/hallazgos' });
    expect(ruta('finops/historial')).toEqual({ redirigir: 'costos/historial' });
    expect(ruta('cumplimiento/activos')).toEqual({ redirigir: 'riesgo/clasificacion' });
    expect(ruta('iso')).toEqual({ redirigir: 'riesgo/cumplimiento' });
    expect(ruta('admin/plataforma')).toEqual({ redirigir: 'plataforma/estado' });
  });

  it('un dominio lleva a su primera sección y lo desconocido al resumen', () => {
    expect(ruta('costos')).toEqual({ redirigir: 'costos/gasto' });
    expect(ruta('no-existe/x')).toEqual({ redirigir: 'inicio/resumen' });
  });
});

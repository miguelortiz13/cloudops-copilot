import { describe, expect, it } from 'vitest';
import { dateRange, dateTime, day, money, moneyAxis, number, percent, plural, shortDate, shortType } from './format';

// Intl separa con espacios no separables; se comparan como espacios normales.
const n = (s: string) => s.replace(/\s/g, ' ');

describe('cifras en es-CO', () => {
  it('moneda: miles con punto, decimales con coma y sin decimales desde mil', () => {
    expect(n(money(1234.5))).toBe('$ 1.235');
    expect(n(money(12.345))).toBe('$ 12,35');
    expect(n(money(-3))).toBe('-$ 3,00');
    expect(n(money(0.5, 'USD', 0))).toBe('$ 1');
  });

  it('un valor ausente se muestra como raya, nunca como 0', () => {
    for (const fn of [money, number, percent]) {
      expect(fn(null)).toBe('—');
      expect(fn(undefined)).toBe('—');
      expect(fn(Number.NaN)).toBe('—');
    }
  });

  it('ejes compactos', () => {
    expect(n(moneyAxis(1500))).toBe('$1,5 K');
    expect(n(moneyAxis(40))).toBe('$ 40');
    expect(n(moneyAxis(12.5))).toBe('$ 12,50');
  });

  it('números, porcentajes y plurales', () => {
    expect(number(1234567)).toBe('1.234.567');
    expect(number(3.14159, 2)).toBe('3,14');
    expect(n(percent(12.345))).toBe('12,3 %');
    expect(plural(1, 'recurso')).toBe('1 recurso');
    expect(plural(3, 'recurso')).toBe('3 recursos');
    expect(plural(1200, 'regla de NSG', 'reglas de NSG')).toBe('1.200 reglas de NSG');
  });
});

describe('fechas', () => {
  it('una fecha ISO sin hora es ese día, no el anterior por la zona horaria', () => {
    expect(n(shortDate('2026-10-01'))).toBe('1 de oct');
    expect(n(day('2026-10-01'))).toBe('1 de oct de 2026');
  });

  it('day() usa el día del texto aunque traiga hora', () => {
    expect(n(day('2026-10-08T23:59:00Z'))).toBe('8 de oct de 2026');
  });

  it('rangos: el año solo una vez si coincide', () => {
    expect(n(dateRange('2026-09-06', '2026-10-05'))).toBe('6 de sept – 5 de oct de 2026');
    expect(n(dateRange('2025-12-20', '2026-01-10'))).toBe('20 de dic de 2025 – 10 de ene de 2026');
  });

  it('fecha y hora en la zona local (UTC-5)', () => {
    expect(n(dateTime('2026-10-10T06:03:00Z'))).toBe('10/10/2026, 1:03 a. m.');
    expect(dateTime(null)).toBe('—');
  });
});

describe('shortType', () => {
  it('quita el proveedor del tipo de recurso', () => {
    expect(shortType('microsoft.storage/storageaccounts')).toBe('storageaccounts');
    expect(shortType('microsoft.network/networksecuritygroups/securityrules')).toBe('networksecuritygroups/securityrules');
    expect(shortType('sinbarra')).toBe('sinbarra');
    expect(shortType(undefined)).toBe('');
  });
});

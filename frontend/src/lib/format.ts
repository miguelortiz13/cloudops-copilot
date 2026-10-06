/** Formato de cifras y fechas, siempre en es-CO. */

const LOCALE = 'es-CO';

export function money(value: number | null | undefined, currency = 'USD', digits?: number): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const abs = Math.abs(value);
  const fraction = digits ?? (abs >= 1000 ? 0 : 2);
  return new Intl.NumberFormat(LOCALE, {
    style: 'currency',
    currency,
    currencyDisplay: 'narrowSymbol',
    minimumFractionDigits: fraction,
    maximumFractionDigits: fraction,
  }).format(value);
}

/** Moneda compacta para ejes: $1,2 mil */
export function moneyAxis(value: number, currency = 'USD'): string {
  if (Math.abs(value) >= 1000) {
    return new Intl.NumberFormat(LOCALE, {
      style: 'currency', currency, currencyDisplay: 'narrowSymbol',
      notation: 'compact', maximumFractionDigits: 1,
    }).format(value);
  }
  return money(value, currency, value % 1 === 0 ? 0 : 2);
}

export function number(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toLocaleString(LOCALE, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function percent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${value.toLocaleString(LOCALE, { minimumFractionDigits: digits, maximumFractionDigits: digits })} %`;
}

export function shortDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString(LOCALE, { day: 'numeric', month: 'short' });
}

export function longDate(iso: string): string {
  const d = new Date(`${iso.length === 10 ? `${iso}T00:00:00` : iso}`);
  return d.toLocaleDateString(LOCALE, { weekday: 'short', day: 'numeric', month: 'long', year: 'numeric' });
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(LOCALE, { dateStyle: 'medium', timeStyle: 'short' });
}

/** microsoft.storage/storageaccounts -> storageaccounts */
export function shortType(type: string | undefined): string {
  if (!type) return '';
  return type.split('/').slice(1).join('/') || type;
}

export function plural(n: number, singular: string, pluralForm?: string): string {
  return `${number(n)} ${n === 1 ? singular : pluralForm ?? `${singular}s`}`;
}

/** Rango corto: "6 sept – 5 oct 2026" */
export function dateRange(fromIso: string, toIso: string): string {
  const a = new Date(`${fromIso}T00:00:00`);
  const b = new Date(`${toIso}T00:00:00`);
  const sameYear = a.getFullYear() === b.getFullYear();
  const left = a.toLocaleDateString(LOCALE, { day: 'numeric', month: 'short', ...(sameYear ? {} : { year: 'numeric' }) });
  const right = b.toLocaleDateString(LOCALE, { day: 'numeric', month: 'short', year: 'numeric' });
  return `${left} – ${right}`;
}

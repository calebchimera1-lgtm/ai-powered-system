export const STORE_TIMEZONE = 'Africa/Nairobi';

const kes = new Intl.NumberFormat('en-KE', {
  style: 'currency',
  currency: 'KES',
  currencyDisplay: 'code',
  minimumFractionDigits: 2,
});

/** Format an amount in Kenyan Shillings, e.g. "KES 1,250.00". */
export function formatKES(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = typeof value === 'string' ? Number(value) : value;
  if (Number.isNaN(n)) return '—';
  return kes.format(n).replace(/ /g, ' ');
}

const dateTime = new Intl.DateTimeFormat('en-KE', {
  timeZone: STORE_TIMEZONE,
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});

const dateOnly = new Intl.DateTimeFormat('en-KE', {
  timeZone: STORE_TIMEZONE,
  day: '2-digit',
  month: 'short',
  year: 'numeric',
});

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : dateTime.format(d);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : dateOnly.format(d);
}

/** Short description of a browser user-agent string for the sessions list. */
export function describeUserAgent(ua: string | null): string {
  if (!ua) return 'Unknown device';
  const browser = /Edg\//.test(ua)
    ? 'Edge'
    : /Chrome\//.test(ua)
      ? 'Chrome'
      : /Firefox\//.test(ua)
        ? 'Firefox'
        : /Safari\//.test(ua)
          ? 'Safari'
          : 'Browser';
  const os = /Android/.test(ua)
    ? 'Android'
    : /iPhone|iPad/.test(ua)
      ? 'iOS'
      : /Windows/.test(ua)
        ? 'Windows'
        : /Mac OS X/.test(ua)
          ? 'macOS'
          : /Linux/.test(ua)
            ? 'Linux'
            : '';
  return os ? `${browser} on ${os}` : browser;
}

/** Parse an API decimal string. */
export function num(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === '') return 0;
  const n = typeof value === 'string' ? Number(value) : value;
  return Number.isFinite(n) ? n : 0;
}

/** "12.000" -> "12", "1.250" -> "1.25"; adds the unit when given. */
export function formatQty(value: string | number | null | undefined, unit?: string): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = num(value);
  const text = new Intl.NumberFormat('en-KE', { maximumFractionDigits: 3 }).format(n);
  return unit ? `${text} ${unit}` : text;
}

export function formatPercent(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  return `${num(value).toFixed(1)}%`;
}

export const MOVEMENT_LABELS: Record<string, string> = {
  OPENING: 'Opening stock',
  PURCHASE_IN: 'Received',
  RETURN_IN: 'Customer return',
  ADJUSTMENT_IN: 'Adjustment (+)',
  SALE_OUT: 'Sold',
  RETURN_TO_SUPPLIER: 'Returned to supplier',
  DAMAGED: 'Damaged',
  EXPIRED: 'Expired',
  ADJUSTMENT_OUT: 'Adjustment (−)',
};

export const REASON_LABELS: Record<string, string> = {
  COUNT_CORRECTION: 'Stock count correction',
  FOUND_STOCK: 'Found stock',
  DATA_ENTRY_ERROR: 'Data entry error',
  THEFT_SUSPECTED: 'Suspected loss',
  INTERNAL_USE: 'Internal use',
  OTHER: 'Other',
};

export const UNIT_LABELS: Record<string, string> = {
  pcs: 'Pieces',
  pack: 'Packs',
  box: 'Boxes',
  dozen: 'Dozens',
  bottle: 'Bottles',
  carton: 'Cartons',
  bag: 'Bags',
  kg: 'Kilograms',
  g: 'Grams',
  l: 'Litres',
  ml: 'Millilitres',
};

export const WHOLE_UNITS = new Set(['pcs', 'pack', 'box', 'dozen', 'bottle', 'carton', 'bag']);

import type { ProductForecast } from '@/api/analytics';

export const PATTERN_LABEL: Record<string, string> = {
  smooth: 'Steady seller',
  erratic: 'Steady but variable',
  intermittent: 'Slow / occasional seller',
  lumpy: 'Occasional, variable amounts',
  insufficient: 'Too few sales to tell',
};

export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export function fmtQty(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return n.toLocaleString('en-KE', { maximumFractionDigits: n < 10 ? 1 : 0 });
}

/** Whole days from today (store calendar) to an ISO date. */
export function daysUntil(iso: string, now: Date = new Date()): number {
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const [y, m, d] = iso.split('-').map(Number);
  return Math.round((Date.UTC(y!, m! - 1, d!) - today) / 86_400_000);
}

/** red: likely to run out before a delivery could arrive; amber: within two lead times. */
export function stockoutTone(p: Pick<ProductForecast, 'stockout_date' | 'lead_time_days'>, now?: Date): 'red' | 'amber' | 'gray' {
  if (!p.stockout_date) return 'gray';
  const d = daysUntil(p.stockout_date, now);
  if (d <= p.lead_time_days) return 'red';
  if (d <= p.lead_time_days * 2) return 'amber';
  return 'gray';
}

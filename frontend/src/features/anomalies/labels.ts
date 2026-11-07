import type { AlertStatus, AnomalyAlert, Severity } from '@/api/analytics';

export const SEVERITY_TONE: Record<Severity, 'red' | 'amber' | 'gray'> = { HIGH: 'red', MEDIUM: 'amber', LOW: 'gray' };
export const SEVERITY_LABEL: Record<Severity, string> = { HIGH: 'High', MEDIUM: 'Medium', LOW: 'Low' };

export const STATUS_LABEL: Record<AlertStatus, string> = {
  OPEN: 'Open',
  INVESTIGATING: 'Investigating',
  RESOLVED_ISSUE_FOUND: 'Issue found',
  RESOLVED_NO_ISSUE: 'No issue',
};
export const STATUS_TONE: Record<AlertStatus, 'amber' | 'blue' | 'red' | 'green'> = {
  OPEN: 'amber',
  INVESTIGATING: 'blue',
  RESOLVED_ISSUE_FOUND: 'red',
  RESOLVED_NO_ISSUE: 'green',
};

export const DETECTOR_LABEL: Record<AnomalyAlert['detector'], string> = {
  RULE: 'Rule',
  ISOLATION_FOREST: 'Pattern model',
  BOTH: 'Rule and pattern model',
};

export const FIGURE_LABEL: Record<string, string> = {
  units_sold: 'Units sold',
  adj_out: 'Units adjusted out',
  adj_in: 'Units adjusted in',
  adj_count: 'Adjustments',
  damaged: 'Written off as damaged',
  returns: 'Units returned',
  refunds: 'Refunds',
  refund_value: 'Refunded (KES)',
  adj_value: 'Adjustments (KES)',
};

const dm = new Intl.DateTimeFormat('en-KE', { day: 'numeric', month: 'short', timeZone: 'UTC' });
export function period(a: Pick<AnomalyAlert, 'period_start' | 'period_end'>): string {
  const s = dm.format(new Date(`${a.period_start}T00:00:00Z`));
  if (a.period_start === a.period_end) return s;
  return `${s} – ${dm.format(new Date(`${a.period_end}T00:00:00Z`))}`;
}

export function subject(a: AnomalyAlert): string {
  return a.entity_type === 'product' ? (a.product?.name ?? 'Product') : (a.subject_user?.full_name ?? 'Staff member');
}

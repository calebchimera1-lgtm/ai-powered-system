import type { Product } from '@/api/types';
import { Badge } from '@/components/ui/Badge';

const LABELS = {
  out: { tone: 'red', text: 'Out of stock' },
  low: { tone: 'amber', text: 'Low stock' },
  ok: { tone: 'green', text: 'In stock' },
  over: { tone: 'blue', text: 'Overstocked' },
} as const;

export function StockBadge({ status }: { status: Product['stock_status'] }) {
  const { tone, text } = LABELS[status];
  return <Badge tone={tone}>{text}</Badge>;
}

export function ExpiryBadge({ date }: { date: string | null }) {
  if (!date) return null;
  const days = Math.ceil((new Date(date).getTime() - Date.now()) / 86_400_000);
  if (days < 0) return <Badge tone="red">Expired stock</Badge>;
  if (days <= 14) return <Badge tone="amber">Expires in {days} d</Badge>;
  return null;
}

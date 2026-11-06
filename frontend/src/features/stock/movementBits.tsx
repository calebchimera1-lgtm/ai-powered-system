import type { Movement, MovementType } from '@/api/types';
import { Badge } from '@/components/ui/Badge';
import { formatQty, MOVEMENT_LABELS } from '@/lib/format';

const TONES: Record<MovementType, 'green' | 'blue' | 'red' | 'amber' | 'gray'> = {
  OPENING: 'gray',
  PURCHASE_IN: 'green',
  RETURN_IN: 'blue',
  ADJUSTMENT_IN: 'blue',
  SALE_OUT: 'gray',
  RETURN_TO_SUPPLIER: 'amber',
  DAMAGED: 'red',
  EXPIRED: 'red',
  ADJUSTMENT_OUT: 'amber',
};

export function MovementTypeBadge({ type }: { type: MovementType }) {
  return <Badge tone={TONES[type]}>{MOVEMENT_LABELS[type] ?? type}</Badge>;
}

export function MovementQty({ m }: { m: Movement }) {
  const n = Number(m.quantity);
  return (
    <span className={`whitespace-nowrap font-medium tabular-nums ${n > 0 ? 'text-brand-700' : 'text-red-600'}`}>
      {n > 0 ? '+' : '−'}
      {formatQty(Math.abs(n), m.product.unit_of_measure)}
    </span>
  );
}

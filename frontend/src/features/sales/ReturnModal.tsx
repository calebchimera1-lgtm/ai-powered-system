import { useState } from 'react';

import { salesApi } from '@/api/sales';
import type { PaymentMethod, Sale, SaleReturn } from '@/api/types';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Select, Textarea } from '@/components/ui/Field';
import { Modal } from '@/components/ui/Modal';
import { errorMessage } from '@/lib/errors';
import { formatKES, formatQty, num } from '@/lib/format';

interface Row {
  qty: string;
  condition: 'RESALEABLE' | 'DAMAGED';
}

/** Choose items from a receipt to return. Refunds use the discounted price paid. */
export function ReturnModal({ sale, onClose, onDone }: { sale: Sale; onClose: () => void; onDone: (r: SaleReturn) => void }) {
  const [rows, setRows] = useState<Record<number, Row>>({});
  const [reason, setReason] = useState('');
  const [method, setMethod] = useState<PaymentMethod>(sale.payment_method);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const returnable = sale.items.filter((i) => num(i.quantity) > num(i.returned_quantity));
  const chosen = returnable.filter((i) => num(rows[i.id]?.qty) > 0);
  const estimate = chosen.reduce((sum, i) => sum + (num(i.line_total) * num(rows[i.id]!.qty)) / num(i.quantity), 0);
  const problems = chosen.map((i) => {
    const q = num(rows[i.id]!.qty);
    if (q > num(i.quantity) - num(i.returned_quantity)) return `${i.product_name}: more than can be returned`;
    if (!Number.isInteger(q) && Number.isInteger(num(i.quantity))) return `${i.product_name}: use a whole number`;
    return null;
  }).filter(Boolean);

  const submit = async () => {
    setError(null);
    setSaving(true);
    try {
      const ret = await salesApi.createReturn(sale.id, {
        items: chosen.map((i) => ({ sale_item_id: i.id, quantity: String(num(rows[i.id]!.qty)), condition: rows[i.id]!.condition })),
        reason: reason.trim(),
        refund_method: method,
      });
      onDone(ret);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open onClose={onClose} busy={saving} size="lg" title={`Return items from ${sale.receipt_number}`}
      description="Enter how many of each item the customer is bringing back."
      footer={<>
        <Button variant="secondary" onClick={onClose} disabled={saving}>Cancel</Button>
        <Button onClick={submit} loading={saving} disabled={chosen.length === 0 || problems.length > 0 || reason.trim().length < 3}>
          Record return {estimate > 0 && `· refund about ${formatKES(estimate)}`}
        </Button>
      </>}>
      <div className="space-y-4">
        {error && <Alert tone="error">{error}</Alert>}
        <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200">
          {returnable.map((i) => {
            const left = num(i.quantity) - num(i.returned_quantity);
            const row = rows[i.id] ?? { qty: '', condition: 'RESALEABLE' as const };
            return (
              <li key={i.id} className="flex flex-wrap items-center gap-3 p-3">
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-gray-900">{i.product_name}</p>
                  <p className="text-xs text-gray-500">Bought {formatQty(i.quantity)} · can return {formatQty(left)} · paid {formatKES(i.line_total)}</p>
                </div>
                <input aria-label={`Quantity of ${i.product_name} to return`} inputMode="decimal" placeholder="0" value={row.qty}
                  onChange={(e) => setRows((r) => ({ ...r, [i.id]: { ...row, qty: e.target.value } }))}
                  className="h-9 w-20 rounded-lg border border-gray-300 text-center text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-brand-500/30" />
                <select aria-label={`Condition of ${i.product_name}`} value={row.condition}
                  onChange={(e) => setRows((r) => ({ ...r, [i.id]: { ...row, condition: e.target.value as Row['condition'] } }))}
                  className="h-9 rounded-lg border border-gray-300 px-2 text-sm">
                  <option value="RESALEABLE">Can be resold</option>
                  <option value="DAMAGED">Damaged / spoilt</option>
                </select>
              </li>
            );
          })}
        </ul>
        {problems.length > 0 && <Alert tone="warning">{problems.join('. ')}</Alert>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Textarea label="Reason" required rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Wrong size, expired on purchase" />
          <Select label="Refund by" value={method} onChange={(e) => setMethod(e.target.value as PaymentMethod)}
            options={[{ value: 'CASH', label: 'Cash' }, { value: 'MPESA', label: 'M-Pesa' }, { value: 'CARD', label: 'Card' }]} />
        </div>
        <p className="text-xs text-gray-500">Resaleable items go back into stock. Damaged items are refunded but not restocked, and count as a stock loss. Cashiers' returns are approved by a Store Manager before the refund is final.</p>
      </div>
    </Modal>
  );
}

import { Trash2 } from 'lucide-react';

import type { Product } from '@/api/types';
import { ProductPicker } from '@/components/ui/ProductPicker';
import { formatKES, num } from '@/lib/format';

export interface EditLine {
  product: { id: number; name: string; sku: string; unit_of_measure: string; tracks_expiry: boolean; vat_rate: string };
  quantity: string;
  unit_cost: string;
  batch_number?: string;
  expiry_date?: string;
  max?: number; // remaining on the purchase order (informational)
}

const input = 'h-9 w-full rounded-lg border border-gray-300 px-2 text-sm tabular-nums focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30';

export function lineFromProduct(p: Product): EditLine {
  return {
    product: { id: p.id, name: p.name, sku: p.sku, unit_of_measure: p.unit_of_measure, tracks_expiry: p.tracks_expiry, vat_rate: p.vat_rate },
    quantity: '',
    unit_cost: p.purchase_price && Number(p.purchase_price) > 0 ? String(Number(p.purchase_price)) : '',
  };
}

/** Editable product lines for purchase orders and goods received (costs excl. VAT). */
export function LinesEditor({
  lines,
  onChange,
  withBatches = false,
}: {
  lines: EditLine[];
  onChange: (lines: EditLine[]) => void;
  withBatches?: boolean;
}) {
  const update = (i: number, patch: Partial<EditLine>) => onChange(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const subtotal = lines.reduce((s, l) => s + num(l.quantity) * num(l.unit_cost), 0);
  const vat = lines.reduce((s, l) => s + Math.round(num(l.quantity) * num(l.unit_cost) * num(l.product.vat_rate)) / 100, 0);

  return (
    <div className="space-y-3">
      <ProductPicker
        label="Add product"
        placeholder="Add a product: scan or type its name"
        showPrice={false}
        onPick={(p) => {
          if (lines.some((l) => l.product.id === p.id)) return;
          onChange([...lines, lineFromProduct(p)]);
        }}
      />
      {lines.length > 0 && (
        <div className="relative overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-3 py-2">Product</th>
                <th className="w-28 px-3 py-2">Quantity</th>
                <th className="w-32 px-3 py-2">Unit cost (excl. VAT)</th>
                {withBatches && <th className="w-36 px-3 py-2">Batch</th>}
                {withBatches && <th className="w-40 px-3 py-2">Expiry</th>}
                <th className="w-28 px-3 py-2 text-right">Line</th>
                <th className="w-10" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {lines.map((l, i) => (
                <tr key={l.product.id}>
                  <td className="px-3 py-2">
                    <p className="font-medium text-gray-900">{l.product.name}</p>
                    <p className="text-xs text-gray-500">{l.product.sku}{l.max !== undefined && ` · ${l.max} outstanding`}</p>
                  </td>
                  <td className="px-3 py-2">
                    <input aria-label={`Quantity of ${l.product.name}`} inputMode="decimal" value={l.quantity} onChange={(e) => update(i, { quantity: e.target.value })} className={input} />
                  </td>
                  <td className="px-3 py-2">
                    <input aria-label={`Unit cost of ${l.product.name}`} inputMode="decimal" value={l.unit_cost} onChange={(e) => update(i, { unit_cost: e.target.value })} className={input} />
                  </td>
                  {withBatches && (
                    <td className="px-3 py-2">
                      <input aria-label={`Batch of ${l.product.name}`} value={l.batch_number ?? ''} onChange={(e) => update(i, { batch_number: e.target.value })} className={input} placeholder="Optional" />
                    </td>
                  )}
                  {withBatches && (
                    <td className="px-3 py-2">
                      {l.product.tracks_expiry ? (
                        <input aria-label={`Expiry of ${l.product.name}`} type="date" required value={l.expiry_date ?? ''} onChange={(e) => update(i, { expiry_date: e.target.value })}
                          className={`${input} ${!l.expiry_date ? 'border-amber-400' : ''}`} />
                      ) : <span className="text-xs text-gray-400">Not tracked</span>}
                    </td>
                  )}
                  <td className="px-3 py-2 text-right tabular-nums">{formatKES(num(l.quantity) * num(l.unit_cost))}</td>
                  <td className="px-2 py-2">
                    <button type="button" aria-label={`Remove ${l.product.name}`} onClick={() => onChange(lines.filter((_, j) => j !== i))} className="rounded p-1 text-gray-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {lines.length > 0 && (
        <dl className="ml-auto w-full max-w-xs space-y-1 text-sm">
          <div className="flex justify-between"><dt className="text-gray-500">Subtotal</dt><dd className="tabular-nums">{formatKES(subtotal)}</dd></div>
          <div className="flex justify-between"><dt className="text-gray-500">VAT</dt><dd className="tabular-nums">{formatKES(vat)}</dd></div>
          <div className="flex justify-between font-semibold"><dt>Total</dt><dd className="tabular-nums">{formatKES(subtotal + vat)}</dd></div>
        </dl>
      )}
    </div>
  );
}

export function lineProblems(lines: EditLine[], withBatches: boolean): string[] {
  const out: string[] = [];
  for (const l of lines) {
    const q = num(l.quantity);
    if (!(q > 0)) out.push(`${l.product.name}: enter a quantity`);
    else if (['pcs', 'pack', 'box', 'dozen', 'bottle', 'carton', 'bag'].includes(l.product.unit_of_measure) && !Number.isInteger(q)) out.push(`${l.product.name}: whole numbers only`);
    if (l.unit_cost === '' || !/^\d+(\.\d{1,4})?$/.test(l.unit_cost.trim())) out.push(`${l.product.name}: enter the unit cost`);
    if (withBatches && l.product.tracks_expiry && !l.expiry_date) out.push(`${l.product.name}: enter the expiry date`);
  }
  return out;
}

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, ClipboardList, PackageCheck } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { forecastsApi, type ReorderGroup } from '@/api/analytics';
import { purchasingApi } from '@/api/purchasing';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { errorMessage } from '@/lib/errors';
import { formatDate, formatKES } from '@/lib/format';

import { fmtQty, stockoutTone } from './labels';

export function ReorderPage() {
  const q = useQuery({ queryKey: ['forecasts', 'reorder'], queryFn: forecastsApi.reorder });
  if (q.isLoading) return <div className="flex justify-center py-20"><Spinner label="Loading…" /></div>;
  if (q.isError || !q.data) return <Alert tone="error">{errorMessage(q.error)}</Alert>;
  return (
    <>
      <PageHeader title="Reorder suggestions" description="Products at or below their reorder point, grouped by supplier. Adjust the quantities and create a draft purchase order to review and send."
        actions={<Link to="/forecasts" className="inline-flex items-center gap-1 text-sm font-medium text-gray-600 hover:text-gray-900"><ArrowLeft className="h-4 w-4" />Demand forecast</Link>} />
      {q.data.length === 0 ? (
        <Card><EmptyState icon={<PackageCheck className="h-6 w-6" aria-hidden />} title="Nothing to reorder" description="Every product has enough stock (plus open orders) to last until a delivery could arrive." /></Card>
      ) : (
        <div className="space-y-4">{q.data.map((g) => <SupplierGroup key={g.supplier_id ?? 'none'} group={g} />)}</div>
      )}
    </>
  );
}

function SupplierGroup({ group }: { group: ReorderGroup }) {
  const navigate = useNavigate();
  const toast = useToast();
  const qc = useQueryClient();
  const [qty, setQty] = useState<Record<number, string>>(() =>
    Object.fromEntries(group.lines.map((l) => [l.product.id, String(Number(l.suggested_quantity))])));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const chosen = group.lines.filter((l) => Number(qty[l.product.id]) > 0);
  const total = chosen.reduce((a, l) => a + Number(qty[l.product.id]) * Number(l.unit_cost ?? 0), 0);

  const createPo = async () => {
    if (!group.supplier_id) return;
    setError(null);
    setSaving(true);
    try {
      const po = await purchasingApi.createOrder({
        supplier_id: group.supplier_id,
        notes: 'Created from reorder suggestions (demand forecast)',
        items: chosen.map((l) => ({ product_id: l.product.id, quantity: qty[l.product.id]!, unit_cost: String(Number(l.unit_cost ?? 0)) })),
      });
      toast.success(`Draft purchase order ${po.po_number} created`);
      void qc.invalidateQueries({ queryKey: ['purchase-orders'] });
      navigate(`/purchasing/orders/${po.id}`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title={group.supplier_name} description={`${group.lines.length} product${group.lines.length === 1 ? '' : 's'} · about ${formatKES(total)} excl. VAT`}
      actions={group.supplier_id
        ? <Button icon={<ClipboardList className="h-4 w-4" />} onClick={createPo} loading={saving} disabled={chosen.length === 0}>Create draft purchase order</Button>
        : <span className="text-xs text-gray-500">Set a usual supplier on these products to order them here.</span>}
      bodyClassName="p-0">
      {error && <div className="p-4"><Alert tone="error">{error}</Alert></div>}
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <caption className="sr-only">Suggested order for {group.supplier_name}</caption>
          <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th className="px-4 py-2">Product</th>
              <th className="px-3 py-2 text-right">In stock</th>
              <th className="hidden px-3 py-2 text-right sm:table-cell">Reorder point</th>
              <th className="px-3 py-2">Runs out</th>
              <th className="px-3 py-2 text-right">Order</th>
              <th className="hidden px-4 py-2 text-right sm:table-cell">Value</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {group.lines.map((l) => {
              const v = qty[l.product.id] ?? '';
              return (
                <tr key={l.product.id}>
                  <td className="px-4 py-2"><Link to={`/forecasts/${l.product.id}`} className="font-medium text-gray-900 hover:text-brand-700">{l.product.name}</Link></td>
                  <td className="px-3 py-2 text-right tabular-nums">{fmtQty(Number(l.on_hand))}{Number(l.on_order) > 0 && <span className="block text-xs text-gray-500">+{fmtQty(Number(l.on_order))} ordered</span>}</td>
                  <td className="hidden px-3 py-2 text-right tabular-nums sm:table-cell">{fmtQty(l.reorder_point)}</td>
                  <td className="px-3 py-2">{l.stockout_date ? <Badge tone={stockoutTone(l)}>{formatDate(l.stockout_date)}</Badge> : '—'}</td>
                  <td className="px-3 py-2 text-right">
                    <input inputMode="decimal" value={v} aria-label={`Quantity of ${l.product.name} to order`} onChange={(e) => setQty((s) => ({ ...s, [l.product.id]: e.target.value.replace(/[^\d.]/g, '') }))}
                      className="h-9 w-20 rounded-lg border border-gray-300 px-2 text-right tabular-nums focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30" />
                    <span className="ml-1 text-xs text-gray-500">{l.product.unit_of_measure}</span>
                  </td>
                  <td className="hidden px-4 py-2 text-right tabular-nums sm:table-cell">{l.unit_cost ? formatKES(Number(v || 0) * Number(l.unit_cost)) : '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

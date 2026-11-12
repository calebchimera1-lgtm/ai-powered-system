import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Printer, RotateCcw } from 'lucide-react';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { salesApi } from '@/api/sales';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { DataTable } from '@/components/ui/DataTable';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { errorMessage } from '@/lib/errors';
import { formatDateTime, formatKES, formatQty } from '@/lib/format';
import { usePageTitle } from '@/hooks/usePageTitle';

import { printReceipt, Receipt } from './Receipt';
import { ReturnModal } from './ReturnModal';
import { METHOD_LABEL, STATUS_BADGE } from './SalesPage';

export function SaleDetailPage() {
  const id = Number(useParams().id);
  const { canAny } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [returning, setReturning] = useState(false);
  const sale = useQuery({ queryKey: ['sale', id], queryFn: () => salesApi.get(id) });
  usePageTitle(sale.data ? `Receipt ${sale.data.receipt_number}` : 'Receipt');
  const store = useQuery({ queryKey: ['store'], queryFn: salesApi.store, staleTime: 10 * 60_000 });
  const returns = useQuery({ queryKey: ['returns', { sale_id: id }], queryFn: () => salesApi.returns({ sale_id: id }) });

  if (sale.isLoading) return <div className="flex justify-center py-20"><Spinner label="Loading…" /></div>;
  if (sale.isError || !sale.data) return <Alert tone="error">{errorMessage(sale.error)}</Alert>;
  const s = sale.data;
  const canReturn = canAny(PERM.RETURNS_REQUEST, PERM.RETURNS_APPROVE) && s.status !== 'RETURNED';

  return (
    <>
      <Link to="/sales" className="mb-2.5 inline-flex items-center gap-1 py-1.5 text-sm text-gray-500 hover:text-gray-800"><ArrowLeft className="h-4 w-4" /> Sales</Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 sm:text-2xl">{s.receipt_number}</h1>
          <p className="mt-1 text-sm text-gray-500">{formatDateTime(s.sold_at)} · {s.cashier.full_name} · {METHOD_LABEL[s.payment_method]}{s.payment_reference && ` ${s.payment_reference}`}</p>
          <div className="mt-2"><Badge tone={STATUS_BADGE[s.status]!.tone}>{STATUS_BADGE[s.status]!.text}</Badge></div>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" icon={<Printer className="h-4 w-4" />} onClick={() => printReceipt(s, store.data)}>Reprint</Button>
          {canReturn && <Button icon={<RotateCcw className="h-4 w-4" />} onClick={() => setReturning(true)}>Return items</Button>}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Items" bodyClassName="p-0">
            <DataTable
              columns={[
                { key: 'p', header: 'Product', render: (i) => <Link to={`/products/${i.product_id}`} className="font-medium text-gray-900 hover:text-brand-700">{i.product_name}</Link> },
                { key: 'q', header: 'Qty', className: 'text-right', render: (i) => (
                  <span className="tabular-nums">{formatQty(i.quantity)}{Number(i.returned_quantity) > 0 && <span className="block text-xs text-amber-700">{formatQty(i.returned_quantity)} returned</span>}</span>
                ) },
                { key: 'u', header: 'Price', className: 'text-right', hideOnMobile: true, render: (i) => <span className="tabular-nums">{formatKES(i.unit_price)}</span> },
                { key: 'd', header: 'Discount', className: 'text-right', hideOnMobile: true, render: (i) => <span className="tabular-nums">{Number(i.discount_amount) > 0 ? formatKES(i.discount_amount) : '—'}</span> },
                { key: 't', header: 'Total', className: 'text-right', render: (i) => <span className="font-medium tabular-nums">{formatKES(i.line_total)}</span> },
                ...(s.cost_total !== null ? [{ key: 'c', header: 'Cost', className: 'text-right', hideOnMobile: true, render: (i: (typeof s.items)[number]) => <span className="tabular-nums text-gray-500">{formatKES(Number(i.unit_cost) * Number(i.quantity))}</span> }] : []),
              ]}
              rows={s.items}
              rowKey={(i) => i.id}
            />
          </Card>
          {(returns.data?.items.length ?? 0) > 0 && (
            <Card title="Returns" bodyClassName="p-0">
              <DataTable
                columns={[
                  { key: 'n', header: 'Return', render: (r) => <span className="font-medium">{r.return_number}</span> },
                  { key: 'i', header: 'Items', render: (r) => <span className="text-xs">{r.items.map((i) => `${formatQty(i.quantity)} × ${i.product_name}${i.condition === 'DAMAGED' ? ' (damaged)' : ''}`).join(', ')}</span> },
                  { key: 'a', header: 'Refund', className: 'text-right', render: (r) => <span className="tabular-nums">{formatKES(r.refund_total)}</span> },
                  { key: 's', header: 'Status', render: (r) => <Badge tone={r.status === 'APPROVED' ? 'green' : r.status === 'PENDING' ? 'amber' : 'gray'}>{r.status === 'PENDING' ? 'Awaiting approval' : r.status === 'APPROVED' ? 'Refunded' : 'Rejected'}</Badge> },
                ]}
                rows={returns.data?.items ?? []}
                rowKey={(r) => r.id}
              />
            </Card>
          )}
        </div>
        <div className="space-y-4">
          <Card title="Totals">
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between"><dt className="text-gray-500">Subtotal</dt><dd className="tabular-nums">{formatKES(s.subtotal)}</dd></div>
              <div className="flex justify-between"><dt className="text-gray-500">Discount</dt><dd className="tabular-nums">{formatKES(s.discount_total)}</dd></div>
              <div className="flex justify-between font-semibold"><dt>Total paid</dt><dd className="tabular-nums">{formatKES(s.grand_total)}</dd></div>
              <div className="flex justify-between"><dt className="text-gray-500">VAT included</dt><dd className="tabular-nums">{formatKES(s.tax_total)}</dd></div>
              {s.cost_total !== null && (
                <>
                  <div className="flex justify-between border-t border-gray-100 pt-2"><dt className="text-gray-500">Cost of goods</dt><dd className="tabular-nums">{formatKES(s.cost_total)}</dd></div>
                  <div className="flex justify-between"><dt className="text-gray-500">Gross profit</dt><dd className="tabular-nums">{formatKES(s.gross_profit)}</dd></div>
                </>
              )}
            </dl>
          </Card>
          <Card title="Receipt"><Receipt sale={s} store={store.data} /></Card>
        </div>
      </div>
      {returning && (
        <ReturnModal sale={s} onClose={() => setReturning(false)} onDone={(r) => {
          setReturning(false);
          toast.success(r.status === 'APPROVED' ? `Refund ${formatKES(r.refund_total)} approved` : 'Return sent for approval', r.return_number);
          qc.invalidateQueries({ queryKey: ['sale', id] });
          qc.invalidateQueries({ queryKey: ['returns'] });
          qc.invalidateQueries({ queryKey: ['products'] });
        }} />
      )}
    </>
  );
}

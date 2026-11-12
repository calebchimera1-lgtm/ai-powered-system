import { useQuery } from '@tanstack/react-query';
import { ArrowLeft } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';

import { purchasingApi } from '@/api/purchasing';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { DataTable } from '@/components/ui/DataTable';
import { Spinner } from '@/components/ui/Spinner';
import { usePageTitle } from '@/hooks/usePageTitle';
import { errorMessage } from '@/lib/errors';
import { formatDate, formatDateTime, formatKES, formatQty } from '@/lib/format';

export function GoodsReceivedDetailPage() {
  const id = Number(useParams().id);
  const q = useQuery({ queryKey: ['purchase', id], queryFn: () => purchasingApi.receipt(id) });
  usePageTitle(q.data ? `Delivery ${q.data.grn_number}` : 'Delivery');
  if (q.isLoading) return <div className="flex justify-center py-20"><Spinner label="Loading…" /></div>;
  if (q.isError || !q.data) return <Alert tone="error">{errorMessage(q.error)}</Alert>;
  const p = q.data;
  return (
    <>
      <Link to="/purchasing/receipts" className="mb-2.5 inline-flex items-center gap-1 py-1.5 text-sm text-gray-500 hover:text-gray-800"><ArrowLeft className="h-4 w-4" /> Goods received</Link>
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900 sm:text-2xl">{p.grn_number}</h1>
        <p className="mt-1 text-sm text-gray-500">
          {p.supplier.name}{p.supplier_invoice_number && ` · invoice ${p.supplier_invoice_number}`}{p.invoice_date && ` dated ${formatDate(p.invoice_date)}`} · received {formatDateTime(p.received_at)} by {p.received_by.full_name}
        </p>
        <div className="mt-2 flex gap-1.5">
          {p.po_number && p.purchase_order_id && <Link to={`/purchasing/orders/${p.purchase_order_id}`}><Badge tone="blue">{p.po_number}</Badge></Link>}
          <Badge>{p.source === 'INVOICE' ? 'From scanned invoice' : 'Entered manually'}</Badge>
        </div>
      </div>
      {p.price_changes.length > 0 && (
        <div className="mb-4"><Alert tone="warning">Supplier price changes: {p.price_changes.map((c) => `${c.product_name} ${formatKES(c.previous_unit_cost)} → ${formatKES(c.new_unit_cost)} (${Number(c.change_percent) > 0 ? '+' : ''}${c.change_percent}%)`).join('; ')}</Alert></div>
      )}
      <Card title="Items" bodyClassName="p-0">
        <DataTable
          columns={[
            { key: 'p', header: 'Product', render: (i) => <Link to={`/products/${i.product.id}`} className="font-medium text-gray-900 hover:text-brand-700">{i.product.name}{(i.batch_number || i.expiry_date) && <span className="block text-xs font-normal text-gray-500">{i.batch_number && `Batch ${i.batch_number}`}{i.expiry_date && ` · expires ${formatDate(i.expiry_date)}`}</span>}</Link> },
            { key: 'q', header: 'Qty', className: 'text-right', render: (i) => formatQty(i.quantity, i.product.unit_of_measure) },
            { key: 'c', header: 'Unit cost', className: 'text-right', render: (i) => (
              <span className="whitespace-nowrap tabular-nums">{formatKES(i.unit_cost)}
                {i.previous_unit_cost && Number(i.previous_unit_cost) !== Number(i.unit_cost) && <span className="block text-xs text-gray-500">was {formatKES(i.previous_unit_cost)}</span>}
              </span>
            ) },
            { key: 'v', header: 'VAT', className: 'text-right', hideOnMobile: true, render: (i) => <span className="tabular-nums">{formatKES(i.tax_amount)}</span> },
            { key: 't', header: 'Total', className: 'text-right', render: (i) => <span className="tabular-nums">{formatKES(i.line_total)}</span> },
          ]}
          rows={p.items}
          rowKey={(i) => i.id}
        />
        <dl className="ml-auto w-full max-w-xs space-y-1 border-t border-gray-100 p-4 text-sm">
          <div className="flex justify-between"><dt className="text-gray-500">Subtotal</dt><dd className="tabular-nums">{formatKES(p.subtotal)}</dd></div>
          <div className="flex justify-between"><dt className="text-gray-500">VAT</dt><dd className="tabular-nums">{formatKES(p.tax_total)}</dd></div>
          <div className="flex justify-between font-semibold"><dt>Total</dt><dd className="tabular-nums">{formatKES(p.grand_total)}</dd></div>
        </dl>
      </Card>
      {p.notes && <div className="mt-4"><Card title="Notes"><p className="text-sm text-gray-700">{p.notes}</p></Card></div>}
    </>
  );
}

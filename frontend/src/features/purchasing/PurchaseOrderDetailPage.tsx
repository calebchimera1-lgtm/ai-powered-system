import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Ban, PackageCheck, Pencil, Send } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { purchasingApi } from '@/api/purchasing';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { DataTable } from '@/components/ui/DataTable';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { errorMessage } from '@/lib/errors';
import { formatDate, formatDateTime, formatKES, formatQty } from '@/lib/format';

import { PO_STATUS } from './PurchaseOrdersPage';

export function PurchaseOrderDetailPage() {
  const id = Number(useParams().id);
  const { can } = useAuth();
  const write = can(PERM.PURCHASES_WRITE);
  const toast = useToast();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [cancelling, setCancelling] = useState(false);
  const po = useQuery({ queryKey: ['purchase-order', id], queryFn: () => purchasingApi.order(id) });
  const receipts = useQuery({ queryKey: ['purchases', { po: id }], queryFn: () => purchasingApi.receipts({ page_size: 50 }), select: (p) => p.items.filter((r) => r.purchase_order_id === id) });
  const act = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['purchase-order', id] }); qc.invalidateQueries({ queryKey: ['purchase-orders'] }); },
    onError: (err) => toast.error('Action failed', errorMessage(err)),
  });

  if (po.isLoading) return <div className="flex justify-center py-20"><Spinner label="Loading…" /></div>;
  if (po.isError || !po.data) return <Alert tone="error">{errorMessage(po.error)}</Alert>;
  const o = po.data;
  const open = ['DRAFT', 'SENT', 'PARTIAL'].includes(o.status);

  return (
    <>
      <Link to="/purchasing/orders" className="mb-4 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-800"><ArrowLeft className="h-4 w-4" /> Purchase orders</Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 sm:text-2xl">{o.po_number}</h1>
          <p className="mt-1 text-sm text-gray-500">{o.supplier.name} · ordered {formatDate(o.order_date)}{o.expected_date && ` · expected ${formatDate(o.expected_date)}`}</p>
          <div className="mt-2"><Badge tone={PO_STATUS[o.status].tone}>{PO_STATUS[o.status].text}</Badge></div>
        </div>
        {write && open && (
          <div className="flex flex-wrap gap-2">
            {o.status === 'DRAFT' && <Button variant="secondary" icon={<Pencil className="h-4 w-4" />} onClick={() => navigate(`/purchasing/orders/${o.id}/edit`)}>Edit</Button>}
            {o.status === 'DRAFT' && <Button variant="secondary" icon={<Send className="h-4 w-4" />} loading={act.isPending} onClick={() => act.mutate(async () => { await purchasingApi.sendOrder(o.id); toast.success('Marked as sent'); })}>Mark as sent</Button>}
            <Button icon={<PackageCheck className="h-4 w-4" />} onClick={() => navigate(`/purchasing/receive?po=${o.id}`)}>Receive goods</Button>
            <Button variant="ghost" icon={<Ban className="h-4 w-4" />} onClick={() => setCancelling(true)}>Cancel order</Button>
          </div>
        )}
      </div>
      <div className="space-y-4">
        <Card title="Products" bodyClassName="p-0">
          <DataTable
            columns={[
              { key: 'p', header: 'Product', render: (i) => <span className="font-medium text-gray-900">{i.product.name}<span className="block text-xs font-normal text-gray-500">{i.product.sku}</span></span> },
              { key: 'o', header: 'Ordered', className: 'text-right', render: (i) => formatQty(i.quantity_ordered, i.product.unit_of_measure) },
              { key: 'r', header: 'Received', className: 'text-right', render: (i) => (
                <span className={Number(i.quantity_received) >= Number(i.quantity_ordered) ? 'text-brand-700' : ''}>{formatQty(i.quantity_received, i.product.unit_of_measure)}</span>
              ) },
              { key: 'c', header: 'Unit cost', className: 'text-right', hideOnMobile: true, render: (i) => <span className="tabular-nums">{formatKES(i.unit_cost)}</span> },
              { key: 't', header: 'Value', className: 'text-right', render: (i) => <span className="tabular-nums">{formatKES(Number(i.quantity_ordered) * Number(i.unit_cost))}</span> },
            ]}
            rows={o.items}
            rowKey={(i) => i.id}
          />
          <p className="border-t border-gray-100 px-4 py-3 text-right text-sm font-semibold">Order value (excl. VAT): {formatKES(o.total)}</p>
        </Card>
        {(receipts.data?.length ?? 0) > 0 && (
          <Card title="Deliveries" bodyClassName="p-0">
            <DataTable
              columns={[
                { key: 'g', header: 'Goods received', render: (r) => <Link to={`/purchasing/receipts/${r.id}`} className="font-medium text-gray-900 hover:text-brand-700">{r.grn_number}</Link> },
                { key: 'i', header: 'Invoice', render: (r) => r.supplier_invoice_number ?? '—' },
                { key: 'd', header: 'Received', render: (r) => <span className="text-xs">{formatDateTime(r.received_at)}</span> },
                { key: 't', header: 'Total', className: 'text-right', render: (r) => <span className="tabular-nums">{formatKES(r.grand_total)}</span> },
              ]}
              rows={receipts.data ?? []}
              rowKey={(r) => r.id}
            />
          </Card>
        )}
        {o.notes && <Card title="Notes"><p className="text-sm text-gray-700">{o.notes}</p></Card>}
      </div>
      <ConfirmDialog open={cancelling} title="Cancel this order?" message="Anything not yet received will no longer be expected. Deliveries already received stay in stock."
        confirmLabel="Cancel order" loading={act.isPending} onCancel={() => setCancelling(false)}
        onConfirm={() => act.mutate(async () => { await purchasingApi.cancelOrder(o.id); toast.success('Order cancelled'); setCancelling(false); })} />
    </>
  );
}

import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { purchasingApi } from '@/api/purchasing';
import type { POStatus, PurchaseOrder } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { DataTable, Pagination, type Column } from '@/components/ui/DataTable';
import { errorMessage } from '@/lib/errors';
import { formatDate, formatKES } from '@/lib/format';

export const PO_STATUS: Record<POStatus, { tone: 'gray' | 'blue' | 'amber' | 'green' | 'red'; text: string }> = {
  DRAFT: { tone: 'gray', text: 'Draft' },
  SENT: { tone: 'blue', text: 'Sent' },
  PARTIAL: { tone: 'amber', text: 'Partly received' },
  RECEIVED: { tone: 'green', text: 'Received' },
  CANCELLED: { tone: 'red', text: 'Cancelled' },
};

const FILTERS = [
  { value: 'OPEN', label: 'Open' },
  { value: 'RECEIVED', label: 'Received' },
  { value: 'CANCELLED', label: 'Cancelled' },
  { value: '', label: 'All' },
];

export function PurchaseOrdersPage() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [status, setStatus] = useState('OPEN');
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ['purchase-orders', { status, page }],
    queryFn: () => purchasingApi.orders({ status, page, page_size: 25 }),
    placeholderData: keepPreviousData,
  });
  const columns: Column<PurchaseOrder>[] = [
    { key: 'no', header: 'Order', render: (po) => <Link to={`/purchasing/orders/${po.id}`} className="whitespace-nowrap font-medium text-gray-900 hover:text-brand-700">{po.po_number}</Link> },
    { key: 'sup', header: 'Supplier', render: (po) => po.supplier.name },
    { key: 'date', header: 'Ordered', hideOnMobile: true, render: (po) => <span className="text-xs">{formatDate(po.order_date)}</span> },
    { key: 'exp', header: 'Expected', hideOnMobile: true, render: (po) => <span className="text-xs">{formatDate(po.expected_date)}</span> },
    { key: 'total', header: 'Value (excl. VAT)', className: 'text-right', render: (po) => <span className="whitespace-nowrap tabular-nums">{formatKES(po.total)}</span> },
    { key: 'status', header: 'Status', render: (po) => <Badge tone={PO_STATUS[po.status].tone}>{PO_STATUS[po.status].text}</Badge> },
  ];
  const data = query.data;
  return (
    <>
      <PageHeader title="Purchase orders" description="What you have ordered from suppliers and what is still to arrive."
        actions={can(PERM.PURCHASES_WRITE) && <Button icon={<Plus className="h-4 w-4" />} onClick={() => navigate('/purchasing/orders/new')}>New order</Button>} />
      <div role="tablist" aria-label="Order status" className="mb-4 flex flex-wrap gap-1 rounded-lg bg-gray-100 p-1 sm:inline-flex">
        {FILTERS.map((f) => (
          <button key={f.value} role="tab" aria-selected={status === f.value} type="button" onClick={() => { setStatus(f.value); setPage(1); }}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${status === f.value ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-600 hover:text-gray-900'}`}>{f.label}</button>
        ))}
      </div>
      <Card bodyClassName="p-0">
        {query.isError ? <div className="p-4"><Alert tone="error">{errorMessage(query.error)}</Alert></div> : (
          <DataTable caption="Purchase orders" columns={columns} rows={data?.items ?? []} rowKey={(po) => po.id} loading={query.isFetching} emptyTitle="No purchase orders" />
        )}
        {data && data.total > 0 && <Pagination page={data.page} pages={data.pages} total={data.total} pageSize={data.page_size} onPageChange={setPage} />}
      </Card>
    </>
  );
}

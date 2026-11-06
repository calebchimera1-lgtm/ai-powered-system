import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { PackageCheck } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { purchasingApi } from '@/api/purchasing';
import type { Purchase } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { DataTable, Pagination, type Column } from '@/components/ui/DataTable';
import { useDebounce } from '@/hooks/useDebounce';
import { errorMessage } from '@/lib/errors';
import { formatDateTime, formatKES } from '@/lib/format';

export function GoodsReceivedPage() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const debounced = useDebounce(search);
  const query = useQuery({
    queryKey: ['purchases', { debounced, page }],
    queryFn: () => purchasingApi.receipts({ search: debounced, page, page_size: 25 }),
    placeholderData: keepPreviousData,
  });
  const columns: Column<Purchase>[] = [
    { key: 'g', header: 'Delivery', render: (p) => <Link to={`/purchasing/receipts/${p.id}`} className="whitespace-nowrap font-medium text-gray-900 hover:text-brand-700">{p.grn_number}{p.po_number && <span className="block text-xs font-normal text-gray-500">{p.po_number}</span>}</Link> },
    { key: 's', header: 'Supplier', render: (p) => p.supplier.name },
    { key: 'i', header: 'Invoice', hideOnMobile: true, render: (p) => p.supplier_invoice_number ?? '—' },
    { key: 'd', header: 'Received', hideOnMobile: true, render: (p) => <span className="whitespace-nowrap text-xs">{formatDateTime(p.received_at)}<span className="block text-gray-500">{p.received_by.full_name}</span></span> },
    { key: 't', header: 'Total (incl. VAT)', className: 'text-right', render: (p) => <span className="whitespace-nowrap tabular-nums">{formatKES(p.grand_total)}</span> },
  ];
  const data = query.data;
  return (
    <>
      <PageHeader title="Goods received" description="Every supplier delivery recorded into stock."
        actions={can(PERM.PURCHASES_WRITE) && <Button icon={<PackageCheck className="h-4 w-4" />} onClick={() => navigate('/purchasing/receive')}>Receive goods</Button>} />
      <Card bodyClassName="p-0">
        <div className="border-b border-gray-100 p-4">
          <input type="search" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} aria-label="Search deliveries" placeholder="Delivery or supplier invoice number"
            className="h-10 w-full rounded-lg border border-gray-300 px-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30" />
        </div>
        {query.isError ? <div className="p-4"><Alert tone="error">{errorMessage(query.error)}</Alert></div> : (
          <DataTable caption="Goods received" columns={columns} rows={data?.items ?? []} rowKey={(p) => p.id} loading={query.isFetching} emptyTitle="No deliveries recorded" />
        )}
        {data && data.total > 0 && <Pagination page={data.page} pages={data.pages} total={data.total} pageSize={data.page_size} onPageChange={setPage} />}
      </Card>
    </>
  );
}

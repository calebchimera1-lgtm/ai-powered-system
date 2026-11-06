import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { X } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';

import { productsApi } from '@/api/catalog';
import { stockApi } from '@/api/stock';
import type { Movement } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { Card, PageHeader } from '@/components/ui/Card';
import { DataTable, Pagination, type Column } from '@/components/ui/DataTable';
import { errorMessage } from '@/lib/errors';
import { formatDateTime, formatKES, formatQty } from '@/lib/format';

import { MovementQty, MovementTypeBadge } from './movementBits';

const TYPE_FILTERS = [
  { value: '', label: 'All movements' },
  { value: 'OPENING,PURCHASE_IN', label: 'Stock received' },
  { value: 'SALE_OUT', label: 'Sold' },
  { value: 'RETURN_IN,RETURN_TO_SUPPLIER', label: 'Returns' },
  { value: 'DAMAGED', label: 'Damaged' },
  { value: 'EXPIRED', label: 'Expired' },
  { value: 'ADJUSTMENT_IN,ADJUSTMENT_OUT', label: 'Manual adjustments' },
];

const control =
  'h-10 rounded-lg border border-gray-300 bg-white px-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30';

export function StockMovementsPage() {
  const { can } = useAuth();
  const canCost = can(PERM.PRODUCTS_VIEW_COST);
  const [params, setParams] = useSearchParams();
  const type = params.get('type') ?? '';
  const productId = params.get('product') ? Number(params.get('product')) : undefined;
  const from = params.get('from') ?? '';
  const to = params.get('to') ?? '';
  const page = Number(params.get('page') ?? 1);

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== 'page') next.delete('page');
    setParams(next, { replace: true });
  };

  const product = useQuery({
    queryKey: ['product', productId],
    queryFn: () => productsApi.get(productId!),
    enabled: Boolean(productId),
  });
  const query = useQuery({
    queryKey: ['movements', { type, productId, from, to, page }],
    queryFn: () =>
      stockApi.movements({ movement_type: type, product_id: productId, date_from: from, date_to: to, page, page_size: 30 }),
    placeholderData: keepPreviousData,
  });

  const columns: Column<Movement>[] = [
    { key: 'when', header: 'When', render: (m) => <span className="whitespace-nowrap text-xs text-gray-600">{formatDateTime(m.created_at)}</span> },
    {
      key: 'product',
      header: 'Product',
      render: (m) => (
        <Link to={`/products/${m.product.id}`} className="block min-w-[10rem] hover:text-brand-700">
          <span className="font-medium text-gray-900">{m.product.name}</span>
          {m.batch_number && <span className="block text-xs text-gray-500">Batch {m.batch_number}</span>}
        </Link>
      ),
    },
    { key: 'type', header: 'Type', render: (m) => <MovementTypeBadge type={m.movement_type} /> },
    { key: 'qty', header: 'Quantity', className: 'text-right', render: (m) => <MovementQty m={m} /> },
    { key: 'balance', header: 'Balance', className: 'text-right', hideOnMobile: true, render: (m) => <span className="tabular-nums">{formatQty(m.balance_after)}</span> },
    ...(canCost
      ? [{ key: 'value', header: 'Value', className: 'text-right', hideOnMobile: true, render: (m: Movement) => <span className="whitespace-nowrap tabular-nums text-gray-600">{formatKES(m.value)}</span> }]
      : []),
    { key: 'user', header: 'By', hideOnMobile: true, render: (m) => <span className="whitespace-nowrap text-xs">{m.user.full_name}</span> },
    { key: 'reason', header: 'Note', hideOnMobile: true, render: (m) => <span className="text-xs text-gray-500">{m.reason ?? '—'}</span> },
  ];

  const data = query.data;
  return (
    <>
      <PageHeader title="Stock movements" description="Every change to stock, with who made it and when. Entries can never be edited or deleted." />
      <Card bodyClassName="p-0">
        <div className="flex flex-col gap-3 border-b border-gray-100 p-4 lg:flex-row lg:items-center">
          <select value={type} onChange={(e) => set('type', e.target.value)} aria-label="Movement type" className={control}>
            {TYPE_FILTERS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
          </select>
          <div className="grid grid-cols-2 gap-3">
            <input type="date" value={from} max={to || undefined} onChange={(e) => set('from', e.target.value)} aria-label="From date" className={control} />
            <input type="date" value={to} min={from || undefined} onChange={(e) => set('to', e.target.value)} aria-label="To date" className={control} />
          </div>
          {productId && (
            <button type="button" onClick={() => set('product', '')} className="inline-flex items-center gap-1.5 self-start rounded-full bg-brand-50 px-3 py-1.5 text-sm font-medium text-brand-700 hover:bg-brand-100 lg:self-auto">
              {product.data?.name ?? 'Product'} <X className="h-3.5 w-3.5" aria-label="Clear product filter" />
            </button>
          )}
        </div>
        {query.isError ? (
          <div className="p-4"><Alert tone="error">{errorMessage(query.error)}</Alert></div>
        ) : (
          <DataTable caption="Stock movements" columns={columns} rows={data?.items ?? []} rowKey={(m) => m.id} loading={query.isFetching} emptyTitle="No stock movements" emptyDescription="Try a wider date range or another type." />
        )}
        {data && data.total > 0 && (
          <Pagination page={data.page} pages={data.pages} total={data.total} pageSize={data.page_size} onPageChange={(p) => set('page', String(p))} />
        )}
      </Card>
    </>
  );
}

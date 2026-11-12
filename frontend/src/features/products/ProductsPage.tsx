import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { AlertTriangle, Boxes, CalendarClock, ImageOff, PackageX, Plus, Search, Wallet } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { productsApi, type ProductListParams } from '@/api/catalog';
import { stockApi } from '@/api/stock';
import type { Product } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { ScanButton } from '@/components/ui/BarcodeScanner';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { DataTable, Pagination, type Column } from '@/components/ui/DataTable';
import { StatCard } from '@/components/ui/StatCard';
import { useToast } from '@/components/ui/Toast';
import { useDebounce } from '@/hooks/useDebounce';
import { errorMessage, parseError } from '@/lib/errors';
import { formatDate, formatKES, formatPercent, formatQty } from '@/lib/format';

import { useCategories } from './hooks';
import { ProductFormModal } from './ProductFormModal';
import { ExpiryBadge, StockBadge } from './StockBadge';

type StockFilter = NonNullable<ProductListParams['stock']>;

const STOCK_FILTERS: { value: '' | StockFilter; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'low', label: 'Low' },
  { value: 'out', label: 'Out' },
  { value: 'expiring', label: 'Expiring' },
  { value: 'over', label: 'Over max' },
];

const control =
  'h-10 rounded-lg border border-gray-300 bg-white px-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30';

export function ProductsPage() {
  const { can } = useAuth();
  const canCost = can(PERM.PRODUCTS_VIEW_COST);
  const canStock = can(PERM.STOCK_READ);
  const navigate = useNavigate();
  const toast = useToast();
  const [params, setParams] = useSearchParams();

  const [search, setSearch] = useState(params.get('search') ?? '');
  const stock = (params.get('stock') ?? '') as '' | StockFilter;
  const categoryId = params.get('category') ?? '';
  const status = (params.get('status') ?? 'active') as 'active' | 'inactive' | 'all';
  const page = Number(params.get('page') ?? 1);
  const debounced = useDebounce(search);
  const [formOpen, setFormOpen] = useState(false);

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== 'page') next.delete('page');
    setParams(next, { replace: true });
  };

  const categories = useCategories();
  const summary = useQuery({ queryKey: ['stock-summary'], queryFn: stockApi.summary, enabled: canStock });
  const query = useQuery({
    queryKey: ['products', { debounced, stock, categoryId, status, page }],
    queryFn: () =>
      productsApi.list({
        search: debounced,
        stock: stock || undefined,
        category_id: categoryId ? Number(categoryId) : undefined,
        status,
        page,
        page_size: 25,
      }),
    placeholderData: keepPreviousData,
  });

  /** Exact barcode/SKU match jumps straight to the product (works with USB scanners too). */
  const openByCode = async (code: string) => {
    try {
      const { product } = await productsApi.lookup(code);
      navigate(`/products/${product.id}`);
    } catch (err) {
      if (parseError(err).code === 'NOT_FOUND') {
        setSearch(code);
        toast.info('No product with that code', 'Add it as a new product, or check the code.');
      } else {
        toast.error('Lookup failed', errorMessage(err));
      }
    }
  };

  const columns: Column<Product>[] = [
    {
      key: 'product',
      header: 'Product',
      render: (p) => (
        <Link to={`/products/${p.id}`} className="flex min-w-[9rem] items-center gap-3 sm:min-w-[13rem]">
          {p.image_url ? (
            <img src={p.thumbnail_url ?? p.image_url} alt="" width={40} height={40} loading="lazy" decoding="async" className="hidden h-10 w-10 shrink-0 rounded-lg border border-gray-200 object-cover sm:block" />
          ) : (
            <span className="hidden h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-gray-300 sm:flex">
              <ImageOff className="h-4 w-4" aria-hidden />
            </span>
          )}
          <span className="min-w-0">
            <span className="block font-medium text-gray-900 hover:text-brand-700">{p.name}</span>
            <span className="block text-xs text-gray-500">
              {p.sku}
              {p.barcode && <span className="hidden sm:inline"> · {p.barcode}</span>}
            </span>
          </span>
        </Link>
      ),
    },
    {
      key: 'category',
      header: 'Category',
      hideOnMobile: true,
      render: (p) => <span className="text-gray-600">{p.category?.name ?? '—'}</span>,
    },
    {
      key: 'price',
      header: 'Price',
      className: 'text-right whitespace-nowrap',
      render: (p) => (
        <div>
          <span className="tabular-nums text-gray-900">{formatKES(p.selling_price)}</span>
          {/* On phones the stock column is hidden, so show stock here instead. */}
          <div className="mt-1 flex flex-col items-end gap-1 md:hidden">
            <span className="text-xs font-medium tabular-nums text-gray-600">{formatQty(p.quantity_on_hand, p.unit_of_measure)}</span>
            {p.stock_status !== 'ok' && <StockBadge status={p.stock_status} />}
          </div>
        </div>
      ),
    },
    ...(canCost
      ? [
          {
            key: 'margin',
            header: 'Margin',
            hideOnMobile: true,
            className: 'text-right',
            render: (p: Product) => <span className="tabular-nums">{formatPercent(p.margin_percent)}</span>,
          },
        ]
      : []),
    {
      key: 'stock',
      header: 'In stock',
      hideOnMobile: true,
      className: 'text-right',
      render: (p) => (
        <div className="flex flex-col items-end gap-1">
          <span className="whitespace-nowrap font-medium tabular-nums text-gray-900">
            {formatQty(p.quantity_on_hand, p.unit_of_measure)}
          </span>
          <div className="flex flex-wrap justify-end gap-1">
            {p.stock_status !== 'ok' && <StockBadge status={p.stock_status} />}
            <ExpiryBadge date={p.next_expiry} />
          </div>
        </div>
      ),
    },
    {
      key: 'expiry',
      header: 'Next expiry',
      hideOnMobile: true,
      render: (p) => <span className="whitespace-nowrap text-xs text-gray-500">{p.tracks_expiry ? formatDate(p.next_expiry) : '—'}</span>,
    },
  ];

  const s = summary.data;
  const data = query.data;

  return (
    <>
      <PageHeader
        title="Products"
        description="Everything the store sells, with live stock levels."
        actions={
          can(PERM.PRODUCTS_WRITE) && (
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => setFormOpen(true)}>
              Add product
            </Button>
          )
        }
      />

      {s && (
        <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-5">
          <StatCard label="Active products" value={s.active_products} icon={Boxes} tone="green" />
          <StatCard label="Low stock" value={s.low_stock} icon={AlertTriangle} tone="amber" to="/products?stock=low" />
          <StatCard label="Out of stock" value={s.out_of_stock} icon={PackageX} tone="red" to="/products?stock=out" />
          <StatCard
            label="Expiring soon"
            value={s.expiring_soon + s.expired_in_stock}
            icon={CalendarClock}
            tone="amber"
            hint={s.expired_in_stock ? `${s.expired_in_stock} already expired` : 'Next 14 days'}
            to="/products?stock=expiring"
          />
          {s.inventory_value !== null && (
            <StatCard label="Stock value (at cost)" value={formatKES(s.inventory_value)} icon={Wallet} tone="blue" />
          )}
        </div>
      )}

      <Card bodyClassName="p-0">
        <div className="space-y-3 border-b border-gray-100 p-4">
          <div className="flex gap-2">
            <form
              className="relative flex-1"
              onSubmit={(e) => {
                e.preventDefault();
                if (search.trim()) openByCode(search.trim());
              }}
            >
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" aria-hidden />
              <input
                type="search"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setParam('page', '');
                }}
                placeholder="Search name, SKU or barcode (press Enter to open)"
                aria-label="Search products"
                className={`${control} w-full pl-9`}
              />
            </form>
            <ScanButton onDetected={openByCode} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div role="group" aria-label="Stock filter" className="flex flex-wrap gap-1 rounded-lg bg-gray-100 p-1">
              {STOCK_FILTERS.map((f) => (
                <button
                  key={f.value}
                  type="button"
                  onClick={() => setParam('stock', f.value)}
                  aria-pressed={stock === f.value}
                  className={`rounded-md px-3 py-2 text-sm font-medium sm:py-1 ${
                    stock === f.value ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-600 hover:text-gray-900'
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <select value={categoryId} onChange={(e) => setParam('category', e.target.value)} aria-label="Category" className={control}>
              <option value="">All categories</option>
              {categories.data?.map((c) => (
                <option key={c.id} value={c.id}>{c.path}</option>
              ))}
            </select>
            <select value={status} onChange={(e) => setParam('status', e.target.value === 'active' ? '' : e.target.value)} aria-label="Status" className={control}>
              <option value="active">Active</option>
              <option value="inactive">Deactivated</option>
              <option value="all">All</option>
            </select>
          </div>
        </div>

        {query.isError ? (
          <div className="p-4"><Alert tone="error">{errorMessage(query.error)}</Alert></div>
        ) : (
          <DataTable
            caption="Products"
            columns={columns}
            rows={data?.items ?? []}
            rowKey={(p) => p.id}
            loading={query.isFetching}
            emptyTitle="No products found"
            emptyDescription={search || stock || categoryId ? 'Try a different search or filter.' : 'Add your first product to get started.'}
          />
        )}
        {data && data.total > 0 && (
          <Pagination page={data.page} pages={data.pages} total={data.total} pageSize={data.page_size} onPageChange={(p) => setParam('page', String(p))} />
        )}
      </Card>

      <ProductFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onSave={async (body) => {
          const created = await productsApi.create(body);
          toast.success(`${created.name} added`, `SKU ${created.sku}`);
          setFormOpen(false);
          navigate(`/products/${created.id}`);
        }}
      />
    </>
  );
}

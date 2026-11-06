import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Barcode,
  ClipboardEdit,
  ImageOff,
  ImagePlus,
  Pencil,
  Power,
  Printer,
  Trash2,
  Trash,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { productsApi } from '@/api/catalog';
import { stockApi } from '@/api/stock';
import type { Product } from '@/api/types';
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
import { AdjustStockModal } from '@/features/stock/AdjustStockModal';
import { MovementQty, MovementTypeBadge } from '@/features/stock/movementBits';
import { WriteOffModal } from '@/features/stock/WriteOffModal';
import { errorMessage } from '@/lib/errors';
import { formatDate, formatDateTime, formatKES, formatPercent, formatQty, UNIT_LABELS } from '@/lib/format';

import { ProductFormModal } from './ProductFormModal';
import { ExpiryBadge, StockBadge } from './StockBadge';

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-2 text-sm">
      <dt className="text-gray-500">{label}</dt>
      <dd className="text-right font-medium text-gray-900">{children}</dd>
    </div>
  );
}

function BarcodeLabel({ product }: { product: Product }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!product.barcode) return;
    let current: string | null = null;
    productsApi.barcodeSvgUrl(product.id).then((u) => {
      current = u;
      setUrl(u);
    }).catch(() => setUrl(null));
    return () => {
      if (current) URL.revokeObjectURL(current);
    };
  }, [product.id, product.barcode]);

  const print = () => {
    if (!url) return;
    const w = window.open('', '_blank', 'width=420,height=320');
    if (!w) return;
    // Built with DOM calls (no inline script), so it works under the site's CSP.
    const doc = w.document;
    doc.title = `Label: ${product.name}`;
    doc.body.style.cssText = 'font-family:sans-serif;text-align:center;margin:16px';
    const title = doc.createElement('div');
    title.textContent = product.name;
    title.style.cssText = 'font-size:14px;margin-bottom:4px';
    const img = doc.createElement('img');
    img.style.width = '260px';
    const price = doc.createElement('div');
    price.textContent = formatKES(product.selling_price);
    price.style.cssText = 'font-size:20px;font-weight:bold;margin-top:4px';
    doc.body.append(title, img, price);
    img.onload = () => {
      w.focus();
      w.print();
    };
    img.src = url;
  };

  if (!product.barcode) return null;
  return (
    <div className="space-y-3">
      <div className="flex justify-center rounded-lg border border-gray-200 bg-white p-3">
        {url ? <img src={url} alt={`Barcode ${product.barcode}`} className="h-24" /> : <Spinner />}
      </div>
      <Button variant="secondary" size="sm" className="w-full" icon={<Printer className="h-4 w-4" />} onClick={print} disabled={!url}>
        Print shelf label
      </Button>
    </div>
  );
}

export function ProductDetailPage() {
  const id = Number(useParams().id);
  const { can } = useAuth();
  const canCost = can(PERM.PRODUCTS_VIEW_COST);
  const canStock = can(PERM.STOCK_READ);
  const toast = useToast();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);

  const [editing, setEditing] = useState(false);
  const [adjusting, setAdjusting] = useState(false);
  const [writingOff, setWritingOff] = useState(false);
  const [confirm, setConfirm] = useState<'toggle' | 'delete' | null>(null);

  const product = useQuery({ queryKey: ['product', id], queryFn: () => productsApi.get(id) });
  const batches = useQuery({
    queryKey: ['product', id, 'batches'],
    queryFn: () => productsApi.batches(id),
    enabled: canStock && Boolean(product.data?.tracks_expiry),
  });
  const suppliers = useQuery({
    queryKey: ['product', id, 'suppliers'],
    queryFn: () => productsApi.suppliers(id),
    enabled: can(PERM.SUPPLIERS_READ),
  });
  const movements = useQuery({
    queryKey: ['movements', { product_id: id }],
    queryFn: () => stockApi.movements({ product_id: id, page_size: 10 }),
    enabled: canStock,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['product', id] });
    qc.invalidateQueries({ queryKey: ['movements'] });
    qc.invalidateQueries({ queryKey: ['products'] });
    qc.invalidateQueries({ queryKey: ['stock-summary'] });
    qc.invalidateQueries({ queryKey: ['adjustments'] });
  };

  const action = useMutation({
    mutationFn: async (fn: () => Promise<unknown>) => fn(),
    onSuccess: refresh,
    onError: (err) => toast.error('Action failed', errorMessage(err)),
  });

  if (product.isLoading) return <div className="flex justify-center py-20"><Spinner label="Loading…" /></div>;
  if (product.isError || !product.data) return <Alert tone="error">{errorMessage(product.error)}</Alert>;
  const p = product.data;
  const unit = p.unit_of_measure;

  const uploadImage = async (file: File | undefined) => {
    if (!file) return;
    action.mutate(async () => {
      await productsApi.uploadImage(p.id, file);
      toast.success('Photo updated');
    });
    if (fileRef.current) fileRef.current.value = '';
  };

  return (
    <>
      <Link to="/products" className="mb-4 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-800">
        <ArrowLeft className="h-4 w-4" /> Products
      </Link>

      <div className="mb-6 flex flex-wrap items-start gap-4">
        <div className="relative">
          {p.image_url ? (
            <img src={p.image_url} alt={p.name} className="h-20 w-20 rounded-xl border border-gray-200 object-cover" />
          ) : (
            <div className="flex h-20 w-20 items-center justify-center rounded-xl bg-gray-100 text-gray-300">
              <ImageOff className="h-7 w-7" aria-hidden />
            </div>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold text-gray-900 sm:text-2xl">{p.name}</h1>
          <p className="mt-1 text-sm text-gray-500">
            {p.sku}
            {p.category && <> · {p.category.name}</>}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {!p.is_active && <Badge tone="gray">Deactivated</Badge>}
            <StockBadge status={p.stock_status} />
            <ExpiryBadge date={p.next_expiry} />
            {p.tracks_expiry && <Badge tone="blue">Expiry tracked</Badge>}
          </div>
        </div>
        <div className="flex w-full flex-wrap gap-2 sm:w-auto">
          {can(PERM.STOCK_ADJUST) && p.is_active && (
            <Button icon={<ClipboardEdit className="h-4 w-4" />} onClick={() => setAdjusting(true)}>Adjust stock</Button>
          )}
          {can(PERM.STOCK_WRITE_OFF) && p.is_active && (
            <Button variant="secondary" icon={<Trash className="h-4 w-4" />} onClick={() => setWritingOff(true)}>Write off</Button>
          )}
          {can(PERM.PRODUCTS_WRITE) && (
            <Button variant="secondary" icon={<Pencil className="h-4 w-4" />} onClick={() => setEditing(true)}>Edit</Button>
          )}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <div className="grid gap-4 sm:grid-cols-2">
            <Card title="Stock">
              <p className="text-3xl font-semibold tabular-nums text-gray-900">{formatQty(p.quantity_on_hand, unit)}</p>
              <dl className="mt-3 divide-y divide-gray-100">
                <Row label="Minimum">{formatQty(p.min_stock_level, unit)}</Row>
                <Row label="Maximum">{p.max_stock_level ? formatQty(p.max_stock_level, unit) : '—'}</Row>
                <Row label="Supplier lead time">{p.reorder_lead_time_days} days</Row>
                {p.stock_value !== undefined && <Row label="Value at cost">{formatKES(p.stock_value)}</Row>}
              </dl>
            </Card>
            <Card title="Price">
              <p className="text-3xl font-semibold tabular-nums text-gray-900">{formatKES(p.selling_price)}</p>
              <dl className="mt-3 divide-y divide-gray-100">
                <Row label="VAT">{Number(p.vat_rate)}% included</Row>
                {canCost && (
                  <>
                    <Row label="Average cost (WAC)">{formatKES(p.avg_cost)}</Row>
                    <Row label="Last purchase price">{formatKES(p.purchase_price)}</Row>
                    <Row label="Gross margin">{formatPercent(p.margin_percent)}</Row>
                  </>
                )}
              </dl>
            </Card>
          </div>

          {p.tracks_expiry && canStock && (
            <Card title="Batches" description="Sold and written off oldest expiry first.">
              <div className="-m-4 sm:-m-5">
                <DataTable
                  columns={[
                    { key: 'batch', header: 'Batch', render: (b) => b.batch_number ?? `#${b.id}` },
                    { key: 'expiry', header: 'Expires', render: (b) => (
                      <span className="whitespace-nowrap">
                        {formatDate(b.expiry_date)}{' '}
                        {b.days_to_expiry !== null && b.days_to_expiry < 0 ? <Badge tone="red">Expired</Badge>
                          : b.days_to_expiry !== null && b.days_to_expiry <= 14 ? <Badge tone="amber">{b.days_to_expiry} d</Badge> : null}
                      </span>
                    ) },
                    { key: 'left', header: 'Remaining', className: 'text-right', render: (b) => <span className="tabular-nums">{formatQty(b.quantity_remaining, unit)}</span> },
                    { key: 'recv', header: 'Received', hideOnMobile: true, render: (b) => <span className="text-xs text-gray-500">{formatDate(b.received_at)}</span> },
                  ]}
                  rows={batches.data ?? []}
                  rowKey={(b) => b.id}
                  loading={batches.isLoading}
                  emptyTitle="No stock in any batch"
                />
              </div>
            </Card>
          )}

          {canStock && (
            <Card title="Recent stock movements" actions={<Link className="text-sm font-medium text-brand-700 hover:underline" to={`/stock/movements?product=${p.id}`}>View all</Link>}>
              <div className="-m-4 sm:-m-5">
                <DataTable
                  columns={[
                    { key: 'when', header: 'When', render: (m) => <span className="whitespace-nowrap text-xs text-gray-600">{formatDateTime(m.created_at)}</span> },
                    { key: 'type', header: 'Type', render: (m) => <MovementTypeBadge type={m.movement_type} /> },
                    { key: 'qty', header: 'Qty', className: 'text-right', render: (m) => <MovementQty m={m} /> },
                    { key: 'bal', header: 'Balance', className: 'text-right', hideOnMobile: true, render: (m) => <span className="tabular-nums">{formatQty(m.balance_after)}</span> },
                    { key: 'who', header: 'By', hideOnMobile: true, render: (m) => <span className="text-xs">{m.user.full_name}</span> },
                    { key: 'why', header: 'Note', hideOnMobile: true, render: (m) => <span className="text-xs text-gray-500">{m.reason ?? '—'}</span> },
                  ]}
                  rows={movements.data?.items ?? []}
                  rowKey={(m) => m.id}
                  loading={movements.isLoading}
                  emptyTitle="No stock movements yet"
                />
              </div>
            </Card>
          )}
        </div>

        <div className="space-y-4">
          <Card title="Barcode">
            {p.barcode ? (
              <BarcodeLabel product={p} />
            ) : (
              <div className="space-y-3 text-sm text-gray-600">
                <p>No barcode yet. Products without a manufacturer barcode can get an in-store one.</p>
                {can(PERM.PRODUCTS_WRITE) && (
                  <Button variant="secondary" size="sm" icon={<Barcode className="h-4 w-4" />} loading={action.isPending}
                    onClick={() => action.mutate(async () => { await productsApi.generateBarcode(p.id); toast.success('Barcode created'); })}>
                    Generate barcode
                  </Button>
                )}
              </div>
            )}
          </Card>

          <Card title="Details">
            <dl className="divide-y divide-gray-100">
              <Row label="Unit">{UNIT_LABELS[unit] ?? unit}</Row>
              <Row label="Barcode">{p.barcode ?? '—'}</Row>
              <Row label="Main supplier">{p.default_supplier?.name ?? '—'}</Row>
              <Row label="Updated">{formatDateTime(p.updated_at)}</Row>
            </dl>
            {p.description && <p className="mt-3 text-sm text-gray-600">{p.description}</p>}
          </Card>

          {suppliers.data && suppliers.data.length > 0 && (
            <Card title="Supplier prices" description="Cheapest first">
              <ul className="divide-y divide-gray-100 text-sm">
                {suppliers.data.map((s) => (
                  <li key={s.supplier_id} className="flex justify-between gap-3 py-2">
                    <Link to={`/suppliers/${s.supplier_id}`} className="text-gray-800 hover:text-brand-700">{s.supplier_name}</Link>
                    <span className="tabular-nums text-gray-900">{s.last_unit_price ? formatKES(s.last_unit_price) : '—'}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {can(PERM.PRODUCTS_WRITE) && (
            <Card title="Photo">
              <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" capture="environment" className="sr-only" aria-label="Product photo"
                onChange={(e) => uploadImage(e.target.files?.[0])} />
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" size="sm" icon={<ImagePlus className="h-4 w-4" />} loading={action.isPending} onClick={() => fileRef.current?.click()}>
                  {p.image_url ? 'Replace photo' : 'Add photo'}
                </Button>
                {p.image_url && (
                  <Button variant="ghost" size="sm" onClick={() => action.mutate(async () => { await productsApi.removeImage(p.id); toast.success('Photo removed'); })}>
                    Remove
                  </Button>
                )}
              </div>
              <p className="mt-2 text-xs text-gray-500">JPEG, PNG or WebP up to 5 MB.</p>
            </Card>
          )}

          {can(PERM.PRODUCTS_DELETE) && (
            <Card title="Danger zone">
              <div className="flex flex-col gap-2">
                <Button variant="secondary" size="sm" icon={<Power className="h-4 w-4" />} onClick={() => setConfirm('toggle')}>
                  {p.is_active ? 'Deactivate product' : 'Reactivate product'}
                </Button>
                <Button variant="ghost" size="sm" className="text-red-600 hover:bg-red-50 hover:text-red-700" icon={<Trash2 className="h-4 w-4" />} onClick={() => setConfirm('delete')}>
                  Delete permanently
                </Button>
              </div>
            </Card>
          )}
        </div>
      </div>

      <ProductFormModal
        open={editing}
        product={p}
        onClose={() => setEditing(false)}
        onSave={async (body) => {
          const { opening_stock: _ignored, ...changes } = body;
          await productsApi.update(p.id, changes);
          toast.success('Product saved');
          setEditing(false);
          refresh();
        }}
      />
      {adjusting && (
        <AdjustStockModal
          open
          product={p}
          batches={batches.data ?? []}
          onClose={() => setAdjusting(false)}
          onDone={(message, applied) => {
            setAdjusting(false);
            (applied ? toast.success : toast.info)(applied ? 'Stock adjusted' : 'Waiting for approval', message);
            refresh();
          }}
        />
      )}
      {writingOff && (
        <WriteOffModal
          open
          product={p}
          batches={batches.data ?? []}
          onClose={() => setWritingOff(false)}
          onDone={(message) => {
            setWritingOff(false);
            toast.success('Written off', message);
            refresh();
          }}
        />
      )}
      <ConfirmDialog
        open={confirm === 'toggle'}
        title={p.is_active ? 'Deactivate this product?' : 'Reactivate this product?'}
        message={p.is_active
          ? `${p.name} will be hidden from product lists and the till. Its stock history is kept and you can reactivate it later.`
          : `${p.name} will appear in product lists and the till again.`}
        confirmLabel={p.is_active ? 'Deactivate' : 'Reactivate'}
        tone={p.is_active ? 'danger' : 'primary'}
        loading={action.isPending}
        onCancel={() => setConfirm(null)}
        onConfirm={() => action.mutate(async () => {
          await productsApi.update(p.id, { is_active: !p.is_active });
          toast.success(p.is_active ? 'Product deactivated' : 'Product reactivated');
          setConfirm(null);
        })}
      />
      <ConfirmDialog
        open={confirm === 'delete'}
        title="Delete permanently?"
        message={`This removes ${p.name} completely. It is only possible for products that never had any stock; otherwise deactivate it instead.`}
        confirmLabel="Delete"
        loading={action.isPending}
        onCancel={() => setConfirm(null)}
        onConfirm={async () => {
          try {
            await productsApi.remove(p.id);
            toast.success('Product deleted');
            qc.invalidateQueries({ queryKey: ['products'] });
            navigate('/products', { replace: true });
          } catch (err) {
            setConfirm(null);
            toast.error('Cannot delete', errorMessage(err));
          }
        }}
      />
    </>
  );
}

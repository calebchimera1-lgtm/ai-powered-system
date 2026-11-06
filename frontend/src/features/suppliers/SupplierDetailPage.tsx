import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Link2, Mail, MapPin, Pencil, Phone, Power, Unlink, UserRound } from 'lucide-react';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { productsApi, suppliersApi } from '@/api/catalog';
import type { SupplierProduct } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { DataTable } from '@/components/ui/DataTable';
import { Input } from '@/components/ui/Field';
import { Modal } from '@/components/ui/Modal';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { useDebounce } from '@/hooks/useDebounce';
import { errorMessage } from '@/lib/errors';
import { formatDate, formatKES } from '@/lib/format';

import { SupplierFormModal } from './SupplierFormModal';

function LinkProductModal({ supplierId, existing, onClose, onDone }: {
  supplierId: number; existing: Set<number>; onClose: () => void; onDone: () => void;
}) {
  const toast = useToast();
  const [search, setSearch] = useState('');
  const [productId, setProductId] = useState<number | null>(null);
  const [sku, setSku] = useState('');
  const [price, setPrice] = useState('');
  const [lead, setLead] = useState('');
  const [saving, setSaving] = useState(false);
  const debounced = useDebounce(search);
  const results = useQuery({
    queryKey: ['products', 'pick', debounced],
    queryFn: () => productsApi.list({ search: debounced, page_size: 8 }),
    enabled: debounced.trim().length > 0,
  });
  const priceOk = price === '' || /^\d+(\.\d{1,2})?$/.test(price);

  const save = async () => {
    if (!productId) return;
    setSaving(true);
    try {
      await suppliersApi.linkProduct(supplierId, productId, {
        supplier_sku: sku.trim() || null, last_unit_price: price || null, lead_time_days: lead ? Number(lead) : null,
      });
      toast.success('Product linked');
      onDone();
    } catch (err) {
      toast.error('Could not link product', errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open onClose={onClose} busy={saving} title="Link a product" description="Record that this supplier sells a product, and their price."
      footer={<>
        <Button variant="secondary" onClick={onClose} disabled={saving}>Cancel</Button>
        <Button onClick={save} loading={saving} disabled={!productId || !priceOk}>Save</Button>
      </>}>
      <div className="space-y-4">
        <Input label="Find product" placeholder="Type a name or SKU" value={search} onChange={(e) => { setSearch(e.target.value); setProductId(null); }} />
        {results.data && (
          <ul className="max-h-48 divide-y divide-gray-100 overflow-y-auto rounded-lg border border-gray-200" role="listbox" aria-label="Products">
            {results.data.items.map((p) => (
              <li key={p.id}>
                <button type="button" role="option" aria-selected={productId === p.id} disabled={existing.has(p.id)}
                  onClick={() => setProductId(p.id)}
                  className={`flex w-full justify-between px-3 py-2 text-left text-sm ${productId === p.id ? 'bg-brand-50 text-brand-800' : 'hover:bg-gray-50'} disabled:cursor-not-allowed disabled:text-gray-400`}>
                  <span>{p.name}</span>
                  <span className="text-xs text-gray-500">{existing.has(p.id) ? 'Already linked' : p.sku}</span>
                </button>
              </li>
            ))}
            {results.data.items.length === 0 && <li className="px-3 py-2 text-sm text-gray-500">No matching products</li>}
          </ul>
        )}
        <div className="grid gap-4 sm:grid-cols-3">
          <Input label="Their code" value={sku} onChange={(e) => setSku(e.target.value)} />
          <Input label="Unit price (KES)" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} error={priceOk ? undefined : 'Enter an amount like 205.50'} />
          <Input label="Lead time (days)" type="number" min={0} value={lead} onChange={(e) => setLead(e.target.value)} />
        </div>
      </div>
    </Modal>
  );
}

export function SupplierDetailPage() {
  const id = Number(useParams().id);
  const { can } = useAuth();
  const canWrite = can(PERM.SUPPLIERS_WRITE);
  const canCost = can(PERM.PRODUCTS_VIEW_COST);
  const toast = useToast();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [linking, setLinking] = useState(false);
  const [unlinking, setUnlinking] = useState<SupplierProduct | null>(null);
  const [toggling, setToggling] = useState(false);

  const supplier = useQuery({ queryKey: ['supplier', id], queryFn: () => suppliersApi.get(id) });
  const products = useQuery({ queryKey: ['supplier', id, 'products'], queryFn: () => suppliersApi.products(id) });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['supplier', id] });
    qc.invalidateQueries({ queryKey: ['suppliers'] });
  };

  if (supplier.isLoading) return <div className="flex justify-center py-20"><Spinner label="Loading…" /></div>;
  if (supplier.isError || !supplier.data) return <Alert tone="error">{errorMessage(supplier.error)}</Alert>;
  const s = supplier.data;

  return (
    <>
      <Link to="/suppliers" className="mb-4 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-800"><ArrowLeft className="h-4 w-4" /> Suppliers</Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 sm:text-2xl">{s.name}</h1>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {s.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="gray">Inactive</Badge>}
            {s.kra_pin && <Badge tone="blue">PIN {s.kra_pin}</Badge>}
            <Badge>{s.payment_terms_days}-day terms</Badge>
          </div>
        </div>
        {canWrite && (
          <div className="flex gap-2">
            <Button variant="secondary" icon={<Pencil className="h-4 w-4" />} onClick={() => setEditing(true)}>Edit</Button>
            <Button variant="secondary" icon={<Power className="h-4 w-4" />} onClick={() => setToggling(true)}>{s.is_active ? 'Deactivate' : 'Reactivate'}</Button>
          </div>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Contact" className="lg:order-2">
          <ul className="space-y-3 text-sm text-gray-700">
            <li className="flex items-center gap-2"><UserRound className="h-4 w-4 text-gray-400" aria-hidden />{s.contact_person ?? '—'}</li>
            <li className="flex items-center gap-2"><Phone className="h-4 w-4 text-gray-400" aria-hidden />{s.phone ? <a className="text-brand-700 hover:underline" href={`tel:${s.phone.replace(/\s/g, '')}`}>{s.phone}</a> : '—'}</li>
            <li className="flex items-center gap-2"><Mail className="h-4 w-4 text-gray-400" aria-hidden />{s.email ? <a className="break-all text-brand-700 hover:underline" href={`mailto:${s.email}`}>{s.email}</a> : '—'}</li>
            <li className="flex gap-2"><MapPin className="mt-0.5 h-4 w-4 shrink-0 text-gray-400" aria-hidden /><span className="whitespace-pre-line">{s.address ?? '—'}</span></li>
          </ul>
          {s.notes && <p className="mt-4 border-t border-gray-100 pt-3 text-sm text-gray-600">{s.notes}</p>}
        </Card>
        <Card title="Products supplied" className="lg:col-span-2 lg:order-1" bodyClassName="p-0"
          actions={canWrite && <Button size="sm" variant="secondary" icon={<Link2 className="h-4 w-4" />} onClick={() => setLinking(true)}>Link product</Button>}>
          <DataTable
            columns={[
              { key: 'p', header: 'Product', render: (l) => <Link to={`/products/${l.product_id}`} className="font-medium text-gray-900 hover:text-brand-700">{l.product_name}<span className="block text-xs font-normal text-gray-500">{l.product_sku}</span></Link> },
              { key: 'code', header: 'Their code', hideOnMobile: true, render: (l) => l.supplier_sku ?? '—' },
              ...(canCost ? [{ key: 'price', header: 'Last price', className: 'text-right', render: (l: SupplierProduct) => <span className="whitespace-nowrap tabular-nums">{l.last_unit_price ? formatKES(l.last_unit_price) : '—'}</span> }] : []),
              { key: 'lead', header: 'Lead time', hideOnMobile: true, render: (l) => (l.lead_time_days !== null ? `${l.lead_time_days} d` : '—') },
              { key: 'upd', header: 'Updated', hideOnMobile: true, render: (l) => <span className="text-xs text-gray-500">{formatDate(l.updated_at)}</span> },
              ...(canWrite ? [{ key: 'x', header: <span className="sr-only">Remove</span>, render: (l: SupplierProduct) => (
                <button type="button" className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-red-600" aria-label={`Unlink ${l.product_name}`} onClick={() => setUnlinking(l)}><Unlink className="h-4 w-4" /></button>
              ) }] : []),
            ]}
            rows={products.data ?? []}
            rowKey={(l) => l.product_id}
            loading={products.isLoading}
            emptyTitle="No products linked yet"
            emptyDescription="Link the products this supplier delivers to compare prices."
          />
        </Card>
      </div>

      <SupplierFormModal open={editing} supplier={s} onClose={() => setEditing(false)} onSave={async (body) => {
        await suppliersApi.update(s.id, body);
        toast.success('Supplier saved');
        setEditing(false);
        refresh();
      }} />
      {linking && (
        <LinkProductModal supplierId={s.id} existing={new Set((products.data ?? []).map((l) => l.product_id))} onClose={() => setLinking(false)}
          onDone={() => { setLinking(false); refresh(); }} />
      )}
      <ConfirmDialog open={Boolean(unlinking)} title="Unlink this product?" message={`${unlinking?.product_name} will no longer be listed for ${s.name}.`} confirmLabel="Unlink"
        onCancel={() => setUnlinking(null)}
        onConfirm={async () => {
          if (!unlinking) return;
          try { await suppliersApi.unlinkProduct(s.id, unlinking.product_id); toast.success('Product unlinked'); refresh(); }
          catch (err) { toast.error('Could not unlink', errorMessage(err)); }
          setUnlinking(null);
        }} />
      <ConfirmDialog open={toggling} title={s.is_active ? 'Deactivate supplier?' : 'Reactivate supplier?'}
        message={s.is_active ? `${s.name} will no longer be offered when creating products or orders. History is kept.` : `${s.name} will be available again.`}
        confirmLabel={s.is_active ? 'Deactivate' : 'Reactivate'} tone={s.is_active ? 'danger' : 'primary'}
        onCancel={() => setToggling(false)}
        onConfirm={async () => {
          try { await suppliersApi.update(s.id, { is_active: !s.is_active }); toast.success('Supplier updated'); refresh(); }
          catch (err) { toast.error('Could not update', errorMessage(err)); }
          setToggling(false);
        }} />
    </>
  );
}

import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Search } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { suppliersApi } from '@/api/catalog';
import type { Supplier } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { DataTable, Pagination, type Column } from '@/components/ui/DataTable';
import { useToast } from '@/components/ui/Toast';
import { useDebounce } from '@/hooks/useDebounce';
import { errorMessage } from '@/lib/errors';
import { PhoneLink } from '@/components/ui/ContactLink';

import { SupplierFormModal } from './SupplierFormModal';

export function SuppliersPage() {
  const { can } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<'active' | 'inactive' | ''>('active');
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const debounced = useDebounce(search);

  const query = useQuery({
    queryKey: ['suppliers', { debounced, status, page }],
    queryFn: () => suppliersApi.list({ search: debounced, is_active: status === '' ? undefined : status === 'active', page, page_size: 25 }),
    placeholderData: keepPreviousData,
  });

  const columns: Column<Supplier>[] = [
    { key: 'name', header: 'Supplier', render: (s) => (
      <Link to={`/suppliers/${s.id}`} className="block min-w-[12rem]">
        <span className="font-medium text-gray-900 hover:text-brand-700">{s.name}</span>
        {s.kra_pin && <span className="block text-xs text-gray-500">PIN {s.kra_pin}</span>}
      </Link>
    ) },
    { key: 'contact', header: 'Contact', render: (s) => (
      <div className="text-xs">
        <p className="text-gray-800">{s.contact_person ?? '—'}</p>
        {s.phone && <PhoneLink phone={s.phone} />}
      </div>
    ) },
    { key: 'products', header: 'Products', className: 'text-right', hideOnMobile: true, render: (s) => <span className="tabular-nums">{s.product_count}</span> },
    { key: 'terms', header: 'Terms', hideOnMobile: true, render: (s) => <span className="whitespace-nowrap text-xs">{s.payment_terms_days} days</span> },
    { key: 'status', header: 'Status', render: (s) => s.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="gray">Inactive</Badge> },
  ];

  const data = query.data;
  return (
    <>
      <PageHeader title="Suppliers" description="Who you buy from, what they supply and at what price."
        actions={can(PERM.SUPPLIERS_WRITE) && <Button icon={<Plus className="h-4 w-4" />} onClick={() => setAdding(true)}>Add supplier</Button>} />
      <Card bodyClassName="p-0">
        <div className="flex flex-col gap-3 border-b border-gray-100 p-4 sm:flex-row">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" aria-hidden />
            <input type="search" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Search name, contact, PIN or phone" aria-label="Search suppliers"
              className="h-10 w-full rounded-lg border border-gray-300 pl-9 pr-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30" />
          </div>
          <select value={status} onChange={(e) => { setStatus(e.target.value as typeof status); setPage(1); }} aria-label="Status"
            className="h-10 rounded-lg border border-gray-300 px-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30">
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="">All</option>
          </select>
        </div>
        {query.isError ? <div className="p-4"><Alert tone="error">{errorMessage(query.error)}</Alert></div> : (
          <DataTable caption="Suppliers" columns={columns} rows={data?.items ?? []} rowKey={(s) => s.id} loading={query.isFetching} emptyTitle="No suppliers found" />
        )}
        {data && data.total > 0 && <Pagination page={data.page} pages={data.pages} total={data.total} pageSize={data.page_size} onPageChange={setPage} />}
      </Card>
      <SupplierFormModal open={adding} onClose={() => setAdding(false)} onSave={async (body) => {
        const s = await suppliersApi.create(body);
        toast.success(`${s.name} added`);
        setAdding(false);
        qc.invalidateQueries({ queryKey: ['suppliers'] });
        navigate(`/suppliers/${s.id}`);
      }} />
    </>
  );
}

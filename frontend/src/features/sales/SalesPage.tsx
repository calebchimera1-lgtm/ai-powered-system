import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Banknote, CreditCard, Receipt as ReceiptIcon, RotateCcw, Smartphone } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { salesApi } from '@/api/sales';
import type { Sale } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Card, PageHeader } from '@/components/ui/Card';
import { DataTable, Pagination, type Column } from '@/components/ui/DataTable';
import { StatCard } from '@/components/ui/StatCard';
import { useToast } from '@/components/ui/Toast';
import { useDebounce } from '@/hooks/useDebounce';
import { errorMessage } from '@/lib/errors';
import { formatDateTime, formatKES } from '@/lib/format';

export const METHOD_LABEL: Record<string, string> = { CASH: 'Cash', MPESA: 'M-Pesa', CARD: 'Card' };
export const STATUS_BADGE: Record<string, { tone: 'green' | 'amber' | 'gray'; text: string }> = {
  COMPLETED: { tone: 'green', text: 'Completed' },
  PARTIALLY_RETURNED: { tone: 'amber', text: 'Part returned' },
  RETURNED: { tone: 'gray', text: 'Returned' },
};

export function todayISO(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Africa/Nairobi' }).format(new Date());
}

const control = 'h-10 rounded-lg border border-gray-300 bg-white px-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30';

export function SalesPage() {
  const { can } = useAuth();
  const all = can(PERM.SALES_READ_ALL);
  const navigate = useNavigate();
  const toast = useToast();
  const [from, setFrom] = useState(todayISO());
  const [to, setTo] = useState(todayISO());
  const [method, setMethod] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const debounced = useDebounce(search);

  const query = useQuery({
    queryKey: ['sales', { from, to, method, debounced, page }],
    queryFn: () => salesApi.list({ date_from: from, date_to: to, payment_method: method, search: debounced, page, page_size: 25 }),
    placeholderData: keepPreviousData,
  });
  const summary = useQuery({
    queryKey: ['sales-summary', { from, to }],
    queryFn: () => salesApi.summary({ date_from: from, date_to: to }),
  });
  const total = (m: string) => summary.data?.by_method.find((r) => r.payment_method === m)?.total ?? '0';

  const columns: Column<Sale>[] = [
    { key: 'no', header: 'Receipt', render: (s) => <Link to={`/sales/${s.id}`} className="whitespace-nowrap font-medium text-gray-900 hover:text-brand-700">{s.receipt_number}</Link> },
    { key: 'when', header: 'Time', render: (s) => <span className="whitespace-nowrap text-xs text-gray-600">{formatDateTime(s.sold_at)}</span> },
    ...(all ? [{ key: 'cashier', header: 'Cashier', hideOnMobile: true, render: (s: Sale) => <span className="text-xs">{s.cashier.full_name}</span> }] : []),
    { key: 'items', header: 'Items', hideOnMobile: true, className: 'text-right', render: (s) => s.items.length },
    { key: 'method', header: 'Paid by', render: (s) => <span className="text-sm">{METHOD_LABEL[s.payment_method]}</span> },
    { key: 'total', header: 'Total', className: 'text-right', render: (s) => <span className="whitespace-nowrap font-medium tabular-nums">{formatKES(s.grand_total)}</span> },
    { key: 'status', header: 'Status', hideOnMobile: true, render: (s) => <Badge tone={STATUS_BADGE[s.status]!.tone}>{STATUS_BADGE[s.status]!.text}</Badge> },
  ];

  const data = query.data;
  return (
    <>
      <PageHeader title={all ? 'Sales' : 'My sales'} description={all ? 'Every receipt, with totals for the cash-up.' : 'Your receipts and your cash-up totals.'} />
      {summary.data && (
        <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-5">
          <StatCard label="Receipts" value={summary.data.count} icon={ReceiptIcon} tone="green" />
          <StatCard label="Cash" value={formatKES(total('CASH'))} icon={Banknote} tone="green" />
          <StatCard label="M-Pesa" value={formatKES(total('MPESA'))} icon={Smartphone} tone="green" />
          <StatCard label="Card" value={formatKES(total('CARD'))} icon={CreditCard} tone="blue" />
          <StatCard label="Refunds" value={formatKES(summary.data.refunds_total)} icon={RotateCcw} tone="amber" hint={`Takings ${formatKES(summary.data.gross_total)}`} />
        </div>
      )}
      <Card bodyClassName="p-0">
        <div className="flex flex-col gap-3 border-b border-gray-100 p-4 lg:flex-row lg:items-center">
          <form className="flex-1" onSubmit={async (e) => {
            e.preventDefault();
            if (!search.trim()) return;
            try { navigate(`/sales/${(await salesApi.byReceipt(search)).id}`); }
            catch (err) { toast.info('Receipt not found', errorMessage(err)); }
          }}>
            <input type="search" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} aria-label="Search receipts"
              placeholder="Receipt number or M-Pesa code (Enter to open)" className={`${control} w-full`} />
          </form>
          <div className="grid grid-cols-2 gap-3 sm:flex">
            <input type="date" value={from} max={to} onChange={(e) => { setFrom(e.target.value); setPage(1); }} aria-label="From" className={control} />
            <input type="date" value={to} min={from} onChange={(e) => { setTo(e.target.value); setPage(1); }} aria-label="To" className={control} />
            <select value={method} onChange={(e) => { setMethod(e.target.value); setPage(1); }} aria-label="Payment method" className={`${control} col-span-2`}>
              <option value="">All payments</option>
              <option value="CASH">Cash</option>
              <option value="MPESA">M-Pesa</option>
              <option value="CARD">Card</option>
            </select>
          </div>
        </div>
        {query.isError ? <div className="p-4"><Alert tone="error">{errorMessage(query.error)}</Alert></div> : (
          <DataTable caption="Sales" columns={columns} rows={data?.items ?? []} rowKey={(s) => s.id} loading={query.isFetching} emptyTitle="No sales in this period" />
        )}
        {data && data.total > 0 && <Pagination page={data.page} pages={data.pages} total={data.total} pageSize={data.page_size} onPageChange={setPage} />}
      </Card>
    </>
  );
}

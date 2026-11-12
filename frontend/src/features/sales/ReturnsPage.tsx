import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, X } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { salesApi } from '@/api/sales';
import type { SaleReturn } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { DataTable, Pagination, type Column } from '@/components/ui/DataTable';
import { Textarea } from '@/components/ui/Field';
import { Modal } from '@/components/ui/Modal';
import { useToast } from '@/components/ui/Toast';
import { errorMessage } from '@/lib/errors';
import { formatDateTime, formatKES, formatQty } from '@/lib/format';

const TABS = [
  { value: 'PENDING', label: 'Waiting for approval' },
  { value: 'APPROVED', label: 'Refunded' },
  { value: 'REJECTED', label: 'Rejected' },
] as const;

export function ReturnsPage() {
  const { can, user } = useAuth();
  const canApprove = can(PERM.RETURNS_APPROVE);
  const toast = useToast();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [tab, setTab] = useState<(typeof TABS)[number]['value']>('PENDING');
  const [page, setPage] = useState(1);
  const [receipt, setReceipt] = useState('');
  const [decision, setDecision] = useState<{ ret: SaleReturn; kind: 'approve' | 'reject' } | null>(null);
  const [note, setNote] = useState('');

  const query = useQuery({
    queryKey: ['returns', { tab, page }],
    queryFn: () => salesApi.returns({ status: tab, page, page_size: 25 }),
    placeholderData: keepPreviousData,
  });
  const decide = useMutation({
    mutationFn: (d: NonNullable<typeof decision>) => (d.kind === 'approve' ? salesApi.approveReturn(d.ret.id, note) : salesApi.rejectReturn(d.ret.id, note)),
    onSuccess: (r) => {
      toast.success(r.status === 'APPROVED' ? `Refund of ${formatKES(r.refund_total)} approved` : 'Return rejected');
      setDecision(null);
      qc.invalidateQueries({ queryKey: ['returns'] });
      qc.invalidateQueries({ queryKey: ['products'] });
    },
    onError: (err) => toast.error('Could not save decision', errorMessage(err)),
  });

  const columns: Column<SaleReturn>[] = [
    { key: 'when', header: 'Requested', render: (r) => (
      <div className="text-xs"><p className="whitespace-nowrap text-gray-600">{formatDateTime(r.created_at)}</p><p className="mt-0.5 text-gray-900">by {r.requested_by.full_name}</p></div>
    ) },
    { key: 'receipt', header: 'Receipt', render: (r) => <Link to={`/sales/${r.sale_id}`} className="whitespace-nowrap font-medium text-gray-900 hover:text-brand-700">{r.receipt_number}<span className="block text-xs font-normal text-gray-500">{r.return_number}</span></Link> },
    { key: 'items', header: 'Items', render: (r) => (
      <div className="min-w-[10rem] text-xs">
        {r.items.map((i) => <p key={i.id}>{formatQty(i.quantity)} × {i.product_name}{i.condition === 'DAMAGED' && <Badge tone="red">damaged</Badge>}</p>)}
        <p className="mt-1 text-gray-500">{r.reason}</p>
      </div>
    ) },
    { key: 'refund', header: 'Refund', className: 'text-right', render: (r) => <span className="whitespace-nowrap font-medium tabular-nums">{formatKES(r.refund_total)}</span> },
    ...(tab !== 'PENDING' ? [{ key: 'by', header: 'Decision', hideOnMobile: true, render: (r: SaleReturn) => <span className="text-xs">{r.decided_by?.full_name}{r.decision_note && `: ${r.decision_note}`}</span> }] : []),
    ...(tab === 'PENDING' && canApprove ? [{ key: 'act', header: <span className="sr-only">Decide</span>, render: (r: SaleReturn) => r.requested_by.id === user?.id ? <span className="text-xs text-gray-400">Your request</span> : (
      <div className="flex flex-col items-stretch gap-1.5">
        <Button size="sm" icon={<Check className="h-4 w-4" />} onClick={() => { setNote(''); setDecision({ ret: r, kind: 'approve' }); }}>Approve</Button>
        <Button size="sm" variant="secondary" icon={<X className="h-4 w-4" />} onClick={() => { setNote(''); setDecision({ ret: r, kind: 'reject' }); }}>Reject</Button>
      </div>
    ) }] : []),
  ];

  const data = query.data;
  return (
    <>
      <PageHeader title="Returns and refunds" description="Customer returns. A Store Manager approves each refund before stock and takings change." />
      <Card className="mb-4">
        <form className="flex flex-col gap-2 sm:flex-row" onSubmit={async (e) => {
          e.preventDefault();
          try { navigate(`/sales/${(await salesApi.byReceipt(receipt)).id}`); }
          catch (err) { toast.info('Receipt not found', errorMessage(err)); }
        }}>
          <input value={receipt} onChange={(e) => setReceipt(e.target.value)} aria-label="Receipt number" placeholder="Receipt number, e.g. RCPT-2026-000123"
            className="h-10 w-full rounded-lg border border-gray-300 px-3 text-sm sm:w-auto sm:flex-1 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30" />
          <Button type="submit" disabled={!receipt.trim()}>Start a return</Button>
        </form>
      </Card>
      <div role="tablist" aria-label="Return status" className="mb-4 flex flex-wrap gap-1 rounded-lg bg-gray-100 p-1 sm:inline-flex">
        {TABS.map((t) => (
          <button key={t.value} role="tab" aria-selected={tab === t.value} type="button" onClick={() => { setTab(t.value); setPage(1); }}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${tab === t.value ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-600 hover:text-gray-900'}`}>{t.label}</button>
        ))}
      </div>
      <Card bodyClassName="p-0">
        {query.isError ? <div className="p-4"><Alert tone="error">{errorMessage(query.error)}</Alert></div> : (
          <DataTable caption="Returns" columns={columns} rows={data?.items ?? []} rowKey={(r) => r.id} loading={query.isFetching} emptyTitle={tab === 'PENDING' ? 'No returns waiting' : 'No returns'} />
        )}
        {data && data.total > 0 && <Pagination page={data.page} pages={data.pages} total={data.total} pageSize={data.page_size} onPageChange={setPage} />}
      </Card>
      <Modal open={Boolean(decision)} onClose={() => setDecision(null)} busy={decide.isPending} size="sm"
        title={decision?.kind === 'approve' ? 'Approve refund?' : 'Reject return?'}
        description={decision ? `${decision.ret.receipt_number}: refund ${formatKES(decision.ret.refund_total)} by ${decision.ret.refund_method === 'MPESA' ? 'M-Pesa' : decision.ret.refund_method.toLowerCase()}` : undefined}
        footer={<>
          <Button variant="secondary" onClick={() => setDecision(null)} disabled={decide.isPending}>Cancel</Button>
          <Button variant={decision?.kind === 'approve' ? 'primary' : 'danger'} loading={decide.isPending} disabled={decision?.kind === 'reject' && !note.trim()} onClick={() => decision && decide.mutate(decision)}>
            {decision?.kind === 'approve' ? 'Approve refund' : 'Reject'}
          </Button>
        </>}>
        <Textarea label={decision?.kind === 'reject' ? 'Reason for rejecting' : 'Note (optional)'} required={decision?.kind === 'reject'} rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
      </Modal>
    </>
  );
}

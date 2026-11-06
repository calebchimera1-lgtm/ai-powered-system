import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, X } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { stockApi } from '@/api/stock';
import type { Adjustment } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { DataTable, Pagination, type Column } from '@/components/ui/DataTable';
import { Checkbox, Textarea } from '@/components/ui/Field';
import { Modal } from '@/components/ui/Modal';
import { useToast } from '@/components/ui/Toast';
import { errorMessage } from '@/lib/errors';
import { formatDateTime, formatKES, formatQty, REASON_LABELS } from '@/lib/format';

const TABS = [
  { value: 'PENDING', label: 'Waiting for approval' },
  { value: 'APPROVED', label: 'Applied' },
  { value: 'REJECTED', label: 'Rejected' },
] as const;

type Decision = { adj: Adjustment; kind: 'approve' | 'reject' } | null;

export function AdjustmentsPage() {
  const { can, user } = useAuth();
  const canApprove = can(PERM.STOCK_ADJUST_APPROVE);
  const canNegative = can(PERM.STOCK_ADJUST_NEGATIVE);
  const toast = useToast();
  const qc = useQueryClient();
  const [tab, setTab] = useState<(typeof TABS)[number]['value']>('PENDING');
  const [page, setPage] = useState(1);
  const [decision, setDecision] = useState<Decision>(null);
  const [note, setNote] = useState('');
  const [allowNegative, setAllowNegative] = useState(false);

  const query = useQuery({
    queryKey: ['adjustments', { tab, page }],
    queryFn: () => stockApi.adjustments({ status: tab, page, page_size: 25 }),
    placeholderData: keepPreviousData,
  });

  const decide = useMutation({
    mutationFn: async (d: NonNullable<Decision>) =>
      d.kind === 'approve' ? stockApi.approve(d.adj.id, note, allowNegative) : stockApi.reject(d.adj.id, note),
    onSuccess: (_, d) => {
      toast.success(d.kind === 'approve' ? 'Adjustment approved and applied' : 'Adjustment rejected');
      setDecision(null);
      qc.invalidateQueries({ queryKey: ['adjustments'] });
      qc.invalidateQueries({ queryKey: ['stock-summary'] });
      qc.invalidateQueries({ queryKey: ['products'] });
      qc.invalidateQueries({ queryKey: ['product', d.adj.product.id] });
    },
    onError: (err) => toast.error('Could not save decision', errorMessage(err)),
  });

  const open = (adj: Adjustment, kind: 'approve' | 'reject') => {
    setNote('');
    setAllowNegative(false);
    setDecision({ adj, kind });
  };

  const columns: Column<Adjustment>[] = [
    {
      key: 'when',
      header: 'Requested',
      render: (a) => (
        <div className="text-xs">
          <p className="whitespace-nowrap text-gray-600">{formatDateTime(a.created_at)}</p>
          <p className="mt-0.5 text-gray-900">by {a.requested_by.full_name}</p>
        </div>
      ),
    },
    {
      key: 'product',
      header: 'Product',
      render: (a) => (
        <Link to={`/products/${a.product.id}`} className="block min-w-[10rem] font-medium text-gray-900 hover:text-brand-700">{a.product.name}</Link>
      ),
    },
    {
      key: 'change',
      header: 'Change',
      className: 'text-right',
      render: (a) => {
        const n = Number(a.quantity_change);
        return (
          <div className="whitespace-nowrap text-right">
            <span className={`font-medium tabular-nums ${n > 0 ? 'text-brand-700' : 'text-red-600'}`}>
              {n > 0 ? '+' : '−'}{formatQty(Math.abs(n), a.product.unit_of_measure)}
            </span>
            <span className="block text-xs text-gray-500">
              {a.counted_quantity !== null ? `counted ${formatQty(a.counted_quantity)} vs ${formatQty(a.system_quantity)}` : `system had ${formatQty(a.system_quantity)}`}
            </span>
          </div>
        );
      },
    },
    ...(a0HasCost(query.data?.items) ? [{ key: 'value', header: 'Value', className: 'text-right', hideOnMobile: true, render: (a: Adjustment) => <span className="whitespace-nowrap tabular-nums">{formatKES(a.value_impact)}</span> }] : []),
    {
      key: 'reason',
      header: 'Reason',
      render: (a) => (
        <div className="min-w-[10rem]">
          <Badge tone={a.reason_code === 'THEFT_SUSPECTED' ? 'amber' : 'gray'}>{REASON_LABELS[a.reason_code]}</Badge>
          {a.notes && <p className="mt-1 text-xs text-gray-500">{a.notes}</p>}
        </div>
      ),
    },
    ...(tab === 'PENDING' ? [] : [{
      key: 'who',
      header: 'Decision',
      hideOnMobile: true,
      render: (a: Adjustment) => (
        <div className="text-xs">
          {a.decided_by && (
            <p className="text-gray-500">
              {tab === 'APPROVED' ? 'Approved' : 'Rejected'} by {a.decided_by.full_name}
              {a.decision_note && `: ${a.decision_note}`}
            </p>
          )}
        </div>
      ),
    }]),
    ...(tab === 'PENDING' && canApprove
      ? [{
          key: 'actions',
          header: <span className="sr-only">Decide</span>,
          render: (a: Adjustment) =>
            a.requested_by.id === user?.id ? (
              <span className="text-xs text-gray-400">Your request</span>
            ) : (
              <div className="flex flex-col items-stretch gap-1.5">
                <Button size="sm" icon={<Check className="h-4 w-4" />} onClick={() => open(a, 'approve')}>Approve</Button>
                <Button size="sm" variant="secondary" icon={<X className="h-4 w-4" />} onClick={() => open(a, 'reject')}>Reject</Button>
              </div>
            ),
        }]
      : []),
  ];

  const data = query.data;
  const pendingNegative = decision?.kind === 'approve' && Number(decision.adj.system_quantity) + Number(decision.adj.quantity_change) < 0;

  return (
    <>
      <PageHeader title="Stock adjustments" description="Manual corrections to stock. Large ones need a Store Manager's approval before they change stock." />
      <div role="tablist" aria-label="Adjustment status" className="mb-4 flex flex-wrap gap-1 rounded-lg bg-gray-100 p-1 sm:inline-flex">
        {TABS.map((t) => (
          <button key={t.value} role="tab" aria-selected={tab === t.value} type="button" onClick={() => { setTab(t.value); setPage(1); }}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${tab === t.value ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-600 hover:text-gray-900'}`}>
            {t.label}
          </button>
        ))}
      </div>
      <Card bodyClassName="p-0">
        {query.isError ? (
          <div className="p-4"><Alert tone="error">{errorMessage(query.error)}</Alert></div>
        ) : (
          <DataTable caption="Stock adjustments" columns={columns} rows={data?.items ?? []} rowKey={(a) => a.id} loading={query.isFetching}
            emptyTitle={tab === 'PENDING' ? 'Nothing waiting for approval' : 'No adjustments'} />
        )}
        {data && data.total > 0 && <Pagination page={data.page} pages={data.pages} total={data.total} pageSize={data.page_size} onPageChange={setPage} />}
      </Card>

      <Modal
        open={Boolean(decision)}
        onClose={() => setDecision(null)}
        busy={decide.isPending}
        size="sm"
        title={decision?.kind === 'approve' ? 'Approve adjustment?' : 'Reject adjustment?'}
        description={decision ? `${decision.adj.product.name}: ${Number(decision.adj.quantity_change) > 0 ? '+' : ''}${formatQty(decision.adj.quantity_change, decision.adj.product.unit_of_measure)}` : undefined}
        footer={
          <>
            <Button variant="secondary" onClick={() => setDecision(null)} disabled={decide.isPending}>Cancel</Button>
            <Button variant={decision?.kind === 'approve' ? 'primary' : 'danger'} loading={decide.isPending}
              disabled={decision?.kind === 'reject' && !note.trim()}
              onClick={() => decision && decide.mutate(decision)}>
              {decision?.kind === 'approve' ? 'Approve and apply' : 'Reject'}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {decision?.kind === 'approve' && (
            <p className="text-sm text-gray-600">The change is applied to the current stock balance as soon as you approve.</p>
          )}
          <Textarea label={decision?.kind === 'reject' ? 'Reason for rejecting' : 'Note (optional)'} required={decision?.kind === 'reject'} rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
          {pendingNegative && canNegative && (
            <Checkbox label="Authorise negative stock" checked={allowNegative} onChange={(e) => setAllowNegative(e.target.checked)} />
          )}
        </div>
      </Modal>
    </>
  );
}

function a0HasCost(items: Adjustment[] | undefined): boolean {
  return Boolean(items?.some((a) => a.value_impact !== null));
}

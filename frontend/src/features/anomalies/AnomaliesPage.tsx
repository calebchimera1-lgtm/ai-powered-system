import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { Package, ScanSearch, ShieldCheck, User } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { anomaliesApi } from '@/api/analytics';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { Pagination } from '@/components/ui/DataTable';
import { EmptyState } from '@/components/ui/EmptyState';
import { useToast } from '@/components/ui/Toast';
import { errorMessage } from '@/lib/errors';
import { formatKES } from '@/lib/format';

import { DETECTOR_LABEL, SEVERITY_LABEL, SEVERITY_TONE, STATUS_LABEL, STATUS_TONE, period, subject } from './labels';

const FILTERS = [
  { value: 'OPEN_ALL', label: 'To review' },
  { value: 'RESOLVED', label: 'Resolved' },
  { value: '', label: 'All' },
];

export function AnomaliesPage() {
  const { can } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [status, setStatus] = useState('OPEN_ALL');
  const [severity, setSeverity] = useState('');
  const [page, setPage] = useState(1);
  const list = useQuery({
    queryKey: ['anomalies', { status, severity, page }],
    queryFn: () => anomaliesApi.list({ status, severity, page, page_size: 20 }),
    placeholderData: keepPreviousData,
  });
  const stats = useQuery({ queryKey: ['anomalies', 'stats'], queryFn: anomaliesApi.stats });
  const [scanning, setScanning] = useState(false);

  const scan = async () => {
    setScanning(true);
    try {
      const r = await anomaliesApi.scan();
      toast.success(r.message, 'New findings appear here in a few seconds.');
      window.setTimeout(() => void qc.invalidateQueries({ queryKey: ['anomalies'] }), 4000);
    } catch (e) {
      toast.error('Could not start a scan', errorMessage(e));
    } finally {
      setScanning(false);
    }
  };

  const s = stats.data;
  const open = (s?.by_status.OPEN ?? 0) + (s?.by_status.INVESTIGATING ?? 0);
  return (
    <>
      <PageHeader title="Irregularities" description="Unusual stock losses, adjustments, write-offs and refunds, found by comparing each day with its own normal. They are prompts to check, not conclusions."
        actions={can(PERM.ANOMALIES_REVIEW) && <Button variant="secondary" icon={<ScanSearch className="h-4 w-4" />} onClick={scan} loading={scanning}>Check now</Button>} />

      {s && (
        <div className="mb-4 grid gap-3 sm:grid-cols-3">
          <Tile label="To review" value={String(open)}
            hint={(['HIGH', 'MEDIUM', 'LOW'] as const).map((k) => `${s.open_by_severity[k] ?? 0} ${SEVERITY_LABEL[k].toLowerCase()}`).join(' · ')} />
          <Tile label="Value at stake (open)" value={formatKES(s.open_value_kes)} hint="Cost of the stock or refunds involved" />
          <Tile label="Confirmed when checked" value={s.precision === null ? '—' : `${Math.round(s.precision * 100)}%`}
            hint={s.reviewed ? `${s.reviewed} reviewed: share that turned out to be a real issue` : 'Shown once alerts have been reviewed'} />
        </div>
      )}

      <Card bodyClassName="p-0">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 p-3">
          <div className="flex flex-wrap gap-1" role="tablist" aria-label="Filter by status">
            {FILTERS.map((f) => (
              <button key={f.label} role="tab" aria-selected={status === f.value} onClick={() => { setStatus(f.value); setPage(1); }}
                className={clsx('rounded-lg px-3 py-1.5 text-sm font-medium', status === f.value ? 'bg-brand-50 text-brand-700' : 'text-gray-600 hover:bg-gray-50')}>
                {f.label}
              </button>
            ))}
          </div>
          <select aria-label="Severity" value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(1); }}
            className="h-9 rounded-lg border border-gray-300 bg-white px-2 text-sm">
            <option value="">All severities</option>
            <option value="HIGH">High</option>
            <option value="MEDIUM">Medium</option>
            <option value="LOW">Low</option>
          </select>
        </div>
        {list.isError && <div className="p-4"><Alert tone="error">{errorMessage(list.error)}</Alert></div>}
        {list.data?.items.length === 0 && (
          <EmptyState icon={<ShieldCheck className="h-6 w-6" aria-hidden />} title={status === 'OPEN_ALL' ? 'Nothing to review' : 'No alerts'}
            description={status === 'OPEN_ALL' ? 'No irregularities found in the last two weeks.' : undefined} />
        )}
        <ul className="divide-y divide-gray-100">
          {list.data?.items.map((a) => (
            <li key={a.id}>
              <Link to={`/anomalies/${a.id}`} className="flex gap-3 px-4 py-3 hover:bg-gray-50 sm:px-5">
                <span className="mt-0.5 self-start rounded-lg bg-gray-100 p-2 text-gray-600" aria-hidden>
                  {a.entity_type === 'product' ? <Package className="h-4 w-4" /> : <User className="h-4 w-4" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-gray-900">{a.kind_label}</span>
                    <Badge tone={SEVERITY_TONE[a.severity]}>{SEVERITY_LABEL[a.severity]}</Badge>
                    {a.status !== 'OPEN' && <Badge tone={STATUS_TONE[a.status]}>{STATUS_LABEL[a.status]}</Badge>}
                  </span>
                  <span className="mt-0.5 block text-sm text-gray-700">{subject(a)} · {period(a)}</span>
                  <span className="mt-0.5 line-clamp-2 block text-sm text-gray-600">{a.explanation}</span>
                  <span className="mt-1 block text-xs text-gray-500">Found by: {DETECTOR_LABEL[a.detector]}</span>
                </span>
                <span className="shrink-0 text-right text-sm tabular-nums text-gray-900">{Number(a.value_kes) > 0 ? formatKES(a.value_kes) : ''}</span>
              </Link>
            </li>
          ))}
        </ul>
        {list.data && list.data.total > 0 && <Pagination page={list.data.page} pages={list.data.pages} total={list.data.total} pageSize={list.data.page_size} onPageChange={setPage} />}
      </Card>
    </>
  );
}

function Tile({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-card">
      <p className="text-sm text-gray-600">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-gray-900">{value}</p>
      <p className="mt-1 text-xs text-gray-500">{hint}</p>
    </div>
  );
}

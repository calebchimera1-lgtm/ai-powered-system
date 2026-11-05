import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Fragment, useState } from 'react';

import { auditApi } from '@/api/audit';
import type { AuditLogOut } from '@/api/types';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Card, PageHeader } from '@/components/ui/Card';
import { Pagination } from '@/components/ui/DataTable';
import { EmptyState } from '@/components/ui/EmptyState';
import { Spinner } from '@/components/ui/Spinner';
import { errorMessage } from '@/lib/errors';
import { describeUserAgent, formatDateTime } from '@/lib/format';

const ACTION_FILTERS = [
  { value: '', label: 'All activity' },
  { value: 'auth', label: 'Sign-ins and sessions' },
  { value: 'auth.login_failed', label: 'Failed sign-ins' },
  { value: 'user', label: 'User administration' },
];

const LABELS: Record<string, string> = {
  'auth.login': 'Signed in',
  'auth.login_failed': 'Failed sign-in',
  'auth.logout': 'Signed out',
  'auth.account_locked': 'Account locked',
  'auth.password_changed': 'Changed password',
  'auth.password_reset': 'Reset password via link',
  'auth.refresh_token_reuse': 'Suspicious session reuse',
  'auth.session_revoked': 'Signed out a device',
  'user.create': 'Created user',
  'user.create_superadmin': 'Created super admin (script)',
  'user.reset_superadmin': 'Reset super admin (script)',
  'user.update': 'Updated user',
  'user.unlock': 'Unlocked user',
  'user.sessions_revoked': 'Signed user out everywhere',
  'user.password_reset_issued': 'Issued password link',
};

function tone(action: string): 'red' | 'amber' | 'green' | 'gray' | 'blue' {
  if (action === 'auth.login_failed' || action === 'auth.refresh_token_reuse') return 'red';
  if (action === 'auth.account_locked') return 'amber';
  if (action === 'auth.login') return 'green';
  if (action.startsWith('user.')) return 'blue';
  return 'gray';
}

function Changes({ entry }: { entry: AuditLogOut }) {
  const keys = Array.from(new Set([...Object.keys(entry.before ?? {}), ...Object.keys(entry.after ?? {})]));
  return (
    <div className="space-y-2 text-xs">
      {keys.length > 0 && (
        <table className="w-full max-w-xl">
          <thead>
            <tr className="text-left text-gray-500">
              <th className="py-1 pr-4 font-medium">Field</th>
              <th className="py-1 pr-4 font-medium">Before</th>
              <th className="py-1 font-medium">After</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k}>
                <td className="py-1 pr-4 font-medium text-gray-700">{k}</td>
                <td className="py-1 pr-4 text-gray-500">{String(entry.before?.[k] ?? '—')}</td>
                <td className="py-1 text-gray-900">{String(entry.after?.[k] ?? '—')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {entry.details && <p className="text-gray-600">{entry.details}</p>}
      <p className="text-gray-500">
        {describeUserAgent(entry.user_agent)} · IP {entry.ip_address ?? 'unknown'}
        {entry.entity_type && ` · ${entry.entity_type} #${entry.entity_id}`}
      </p>
    </div>
  );
}

export function AuditLogPage() {
  const [action, setAction] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<number | null>(null);

  const query = useQuery({
    queryKey: ['audit', { action, dateFrom, dateTo, page }],
    queryFn: () => auditApi.list({ action, date_from: dateFrom, date_to: dateTo, page, page_size: 25 }),
    placeholderData: keepPreviousData,
  });
  const data = query.data;
  const input =
    'h-10 rounded-lg border border-gray-300 px-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30';

  return (
    <>
      <PageHeader title="Audit log" description="Who did what, and when. Times are in East Africa Time." />
      <Card bodyClassName="p-0">
        <div className="grid gap-3 border-b border-gray-100 p-4 sm:grid-cols-3">
          <select value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }} aria-label="Activity type" className={input}>
            {ACTION_FILTERS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
          </select>
          <input type="date" value={dateFrom} max={dateTo || undefined} onChange={(e) => { setDateFrom(e.target.value); setPage(1); }} aria-label="From date" className={input} />
          <input type="date" value={dateTo} min={dateFrom || undefined} onChange={(e) => { setDateTo(e.target.value); setPage(1); }} aria-label="To date" className={input} />
        </div>

        {query.isError && <div className="p-4"><Alert tone="error">{errorMessage(query.error)}</Alert></div>}
        {query.isLoading && <div className="flex justify-center py-12"><Spinner label="Loading…" /></div>}
        {data && data.items.length === 0 && <EmptyState title="No activity found" description="Try a wider date range." />}

        {data && data.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="w-8" />
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">When</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Who</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Activity</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.items.map((e) => (
                  <Fragment key={e.id}>
                    <tr className="cursor-pointer hover:bg-gray-50/70" onClick={() => setExpanded(expanded === e.id ? null : e.id)}>
                      <td className="pl-3 text-gray-400">
                        <button type="button" aria-label={expanded === e.id ? 'Hide details' : 'Show details'} aria-expanded={expanded === e.id}>
                          {expanded === e.id ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                        </button>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-gray-600">{formatDateTime(e.created_at)}</td>
                      <td className="px-4 py-3">
                        {e.user ? (
                          <span className="whitespace-nowrap"><span className="font-medium text-gray-900">{e.user.full_name}</span> <span className="text-xs text-gray-500">@{e.user.username}</span></span>
                        ) : (
                          <span className="text-gray-500">System / unknown</span>
                        )}
                      </td>
                      <td className="px-4 py-3"><Badge tone={tone(e.action)}>{LABELS[e.action] ?? e.action}</Badge></td>
                    </tr>
                    {expanded === e.id && (
                      <tr className="bg-gray-50/60">
                        <td />
                        <td colSpan={3} className="px-4 py-3"><Changes entry={e} /></td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && data.total > 0 && (
          <Pagination page={data.page} pages={data.pages} total={data.total} pageSize={data.page_size} onPageChange={setPage} />
        )}
      </Card>
    </>
  );
}

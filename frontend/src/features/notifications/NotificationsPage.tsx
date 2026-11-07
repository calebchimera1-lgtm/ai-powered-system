import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { notificationsApi } from '@/api/analytics';
import { SeverityIcon } from '@/components/layout/NotificationBell';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { errorMessage } from '@/lib/errors';
import { formatDateTime } from '@/lib/format';

const PAGE = 25;

export function NotificationsPage() {
  const qc = useQueryClient();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [page, setPage] = useState(0);
  const q = useQuery({
    queryKey: ['notifications', 'page', { unreadOnly, page }],
    queryFn: () => notificationsApi.list({ unread: unreadOnly || undefined, limit: PAGE, offset: page * PAGE }),
    placeholderData: keepPreviousData,
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ['notifications'] });
  const data = q.data;

  return (
    <>
      <PageHeader title="Notifications" description="Stock, expiry, approvals, forecasts and irregularities that need your attention."
        actions={data && data.unread > 0 && <Button variant="secondary" onClick={async () => { await notificationsApi.markRead(); refresh(); }}>Mark all as read</Button>} />
      <Card bodyClassName="p-0">
        <div className="flex gap-1 border-b border-gray-100 p-3" role="tablist" aria-label="Filter notifications">
          {[{ v: false, l: 'All' }, { v: true, l: `Unread${data ? ` (${data.unread})` : ''}` }].map((t) => (
            <button key={t.l} role="tab" aria-selected={unreadOnly === t.v} onClick={() => { setUnreadOnly(t.v); setPage(0); }}
              className={clsx('rounded-lg px-3 py-1.5 text-sm font-medium', unreadOnly === t.v ? 'bg-brand-50 text-brand-700' : 'text-gray-600 hover:bg-gray-50')}>
              {t.l}
            </button>
          ))}
        </div>
        {q.isError && <div className="p-4"><Alert tone="error">{errorMessage(q.error)}</Alert></div>}
        {data && data.items.length === 0 && <EmptyState title={unreadOnly ? 'No unread notifications' : 'No notifications yet'} />}
        <ul className="divide-y divide-gray-100">
          {data?.items.map((n) => (
            <li key={n.id} className={clsx('flex gap-3 px-4 py-3 sm:px-5', !n.is_read && 'bg-brand-50/40')}>
              <SeverityIcon severity={n.severity} className="mt-0.5 h-5 w-5 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className={clsx('text-sm', n.is_read ? 'text-gray-800' : 'font-semibold text-gray-900')}>{n.title}</p>
                <p className="mt-0.5 text-sm text-gray-600">{n.message}</p>
                <p className="mt-1 flex flex-wrap gap-x-3 text-xs text-gray-500">
                  {formatDateTime(n.created_at)}
                  {n.link && <Link to={n.link} onClick={() => !n.is_read && void notificationsApi.markRead([n.id]).then(refresh)} className="font-medium text-brand-700 hover:underline">Open</Link>}
                  {!n.is_read && <button type="button" className="font-medium text-gray-600 hover:underline" onClick={() => void notificationsApi.markRead([n.id]).then(refresh)}>Mark as read</button>}
                </p>
              </div>
            </li>
          ))}
        </ul>
        {data && data.total > PAGE && (
          <div className="flex items-center justify-between border-t border-gray-100 px-4 py-3 text-sm text-gray-600">
            <span>{page * PAGE + 1}–{Math.min((page + 1) * PAGE, data.total)} of {data.total}</span>
            <span className="flex gap-2">
              <Button size="sm" variant="secondary" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</Button>
              <Button size="sm" variant="secondary" disabled={(page + 1) * PAGE >= data.total} onClick={() => setPage((p) => p + 1)}>Next</Button>
            </span>
          </div>
        )}
      </Card>
    </>
  );
}

import { useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { AlertOctagon, AlertTriangle, Bell, Info } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { notificationsApi, type AppNotification } from '@/api/analytics';
import { formatDateTime } from '@/lib/format';

export function SeverityIcon({ severity, className }: { severity: AppNotification['severity']; className?: string }) {
  if (severity === 'critical') return <AlertOctagon className={clsx('text-red-600', className)} aria-label="Urgent" />;
  if (severity === 'warning') return <AlertTriangle className={clsx('text-amber-600', className)} aria-label="Warning" />;
  return <Info className={clsx('text-blue-600', className)} aria-label="Information" />;
}

/** Bell with unread count; the dropdown shows the latest notifications. */
export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const count = useQuery({ queryKey: ['notifications', 'count'], queryFn: notificationsApi.unreadCount, refetchInterval: 60_000 });
  const latest = useQuery({ queryKey: ['notifications', 'latest'], queryFn: () => notificationsApi.list({ limit: 8 }), enabled: open });

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const refresh = () => void qc.invalidateQueries({ queryKey: ['notifications'] });
  const openItem = async (n: AppNotification) => {
    setOpen(false);
    if (!n.is_read) await notificationsApi.markRead([n.id]).catch(() => undefined);
    refresh();
    if (n.link) navigate(n.link);
  };
  const unread = count.data ?? 0;

  return (
    <div className="relative" ref={ref}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-haspopup="dialog" aria-expanded={open}
        aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}
        className="relative rounded-lg p-2 text-gray-600 hover:bg-gray-100 hover:text-gray-900">
        <Bell className="h-5 w-5" aria-hidden />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-red-600 px-1 text-[11px] font-semibold text-white" aria-hidden>
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>
      {open && (
        <div role="dialog" aria-label="Notifications" className="absolute right-0 mt-2 w-[min(24rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-gray-200 bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-2.5">
            <p className="text-sm font-semibold text-gray-900">Notifications</p>
            {unread > 0 && (
              <button type="button" className="text-xs font-medium text-brand-700 hover:underline"
                onClick={async () => { await notificationsApi.markRead(); refresh(); }}>
                Mark all as read
              </button>
            )}
          </div>
          <ul className="max-h-96 divide-y divide-gray-100 overflow-y-auto">
            {latest.isLoading && <li className="px-4 py-6 text-center text-sm text-gray-500">Loading…</li>}
            {latest.data?.items.length === 0 && <li className="px-4 py-6 text-center text-sm text-gray-500">You are all caught up.</li>}
            {latest.data?.items.map((n) => (
              <li key={n.id}>
                <button type="button" onClick={() => void openItem(n)} className={clsx('flex w-full gap-3 px-4 py-3 text-left hover:bg-gray-50', !n.is_read && 'bg-brand-50/40')}>
                  <SeverityIcon severity={n.severity} className="mt-0.5 h-4 w-4 shrink-0" />
                  <span className="min-w-0 flex-1">
                    <span className={clsx('block text-sm', n.is_read ? 'text-gray-700' : 'font-semibold text-gray-900')}>{n.title}</span>
                    <span className="mt-0.5 line-clamp-2 block text-xs text-gray-600">{n.message}</span>
                    <span className="mt-1 block text-[11px] text-gray-400">{formatDateTime(n.created_at)}</span>
                  </span>
                  {!n.is_read && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand-600" aria-label="Unread" />}
                </button>
              </li>
            ))}
          </ul>
          <Link to="/notifications" onClick={() => setOpen(false)} className="block border-t border-gray-100 px-4 py-2.5 text-center text-sm font-medium text-brand-700 hover:bg-gray-50">
            See all notifications
          </Link>
        </div>
      )}
    </div>
  );
}

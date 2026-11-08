import { useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, DatabaseBackup, Download } from 'lucide-react';
import { useState } from 'react';

import { backupsApi } from '@/api/analytics';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { errorMessage } from '@/lib/errors';
import { formatDateTime } from '@/lib/format';

const mb = (bytes: number) => (bytes < 1e6 ? `${(bytes / 1e3).toFixed(0)} KB` : `${(bytes / 1e6).toFixed(1)} MB`);

export function BackupsPage() {
  const toast = useToast();
  const qc = useQueryClient();
  const [starting, setStarting] = useState(false);
  const q = useQuery({
    queryKey: ['backups'],
    queryFn: backupsApi.list,
    refetchInterval: (query) => (query.state.data?.running ? 2000 : false),
  });

  const start = async () => {
    setStarting(true);
    try {
      await backupsApi.create();
      await qc.invalidateQueries({ queryKey: ['backups'] });
    } catch (e) {
      toast.error('Could not start a backup', errorMessage(e));
    } finally {
      setStarting(false);
    }
  };
  const download = async (name: string, file: string) => {
    try {
      await backupsApi.download(name, file);
    } catch (e) {
      toast.error('Download failed', errorMessage(e));
    }
  };

  const d = q.data;
  return (
    <>
      <PageHeader title="Backups" description="A copy of the database and uploaded files is made every night. Keep a recent copy somewhere other than this computer."
        actions={<Button icon={<DatabaseBackup className="h-4 w-4" />} onClick={start} loading={starting || d?.running}>{d?.running ? 'Backing up…' : 'Back up now'}</Button>} />
      {d?.last_error && <div className="mb-4"><Alert tone="error">The last backup failed: {d.last_error.split('\n').slice(-2).join(' ')}</Alert></div>}
      {d && (
        <p className="mb-4 text-sm text-gray-600">
          Kept automatically: the last {d.policy.daily} nightly backups, one a week for {d.policy.weekly} weeks, and the last {d.policy.manual} made with “Back up now”.
          Restoring replaces all current data, so it is done from the command line with the app stopped (<code className="rounded bg-gray-100 px-1">make restore NAME=…</code>, see the installation guide).
        </p>
      )}
      <Card bodyClassName="p-0">
        {q.isLoading && <div className="flex justify-center py-12"><Spinner label="Loading…" /></div>}
        {q.isError && <div className="p-4"><Alert tone="error">{errorMessage(q.error)}</Alert></div>}
        {d && d.backups.length === 0 && <EmptyState title="No backups yet" description="The first nightly backup runs when the worker starts. You can also back up now." />}
        {d && d.backups.length > 0 && (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <caption className="sr-only">Backups</caption>
              <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-4 py-2">Made</th>
                  <th className="px-3 py-2">Type</th>
                  <th className="hidden px-3 py-2 sm:table-cell">Contents</th>
                  <th className="px-3 py-2 text-right">Size</th>
                  <th className="px-4 py-2 text-right">Download</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {d.backups.map((b) => (
                  <tr key={b.name}>
                    <td className="px-4 py-2.5">
                      <span className="font-medium text-gray-900">{formatDateTime(b.created_at)}</span>
                      <span className="flex items-center gap-1 text-xs text-gray-500">
                        {b.verified && <CheckCircle2 className="h-3.5 w-3.5 text-brand-600" aria-hidden />}
                        {b.verified ? 'Checked readable' : 'Not checked'} · {b.name}
                      </span>
                    </td>
                    <td className="px-3 py-2.5"><Badge tone={b.kind === 'manual' ? 'blue' : 'gray'}>{b.kind === 'manual' ? 'Manual' : 'Nightly'}</Badge></td>
                    <td className="hidden px-3 py-2.5 text-xs text-gray-600 sm:table-cell">
                      {b.row_counts.products} products · {(b.row_counts.sales ?? 0).toLocaleString()} sales · {(b.row_counts.stock_movements ?? 0).toLocaleString()} stock movements
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{mb(b.total_bytes)}</td>
                    <td className="px-4 py-2.5 text-right">
                      <span className="inline-flex gap-1">
                        <Button size="sm" variant="ghost" icon={<Download className="h-4 w-4" />} onClick={() => void download(b.name, 'database.dump')} aria-label={`Download database of ${b.name}`}>Database</Button>
                        <Button size="sm" variant="ghost" icon={<Download className="h-4 w-4" />} onClick={() => void download(b.name, 'files.tar.gz')} aria-label={`Download files of ${b.name}`}>Files</Button>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Archive, ExternalLink, Loader2, RotateCcw } from 'lucide-react';
import { useEffect } from 'react';

import { invoicesApi, type Invoice } from '@/api/invoices';
import { useToast } from '@/components/ui/Toast';
import { errorMessage } from '@/lib/errors';

/** Where an approved invoice stands in the document archive. */
export function ArchiveStatus({ inv, canRetry }: { inv: Invoice; canRetry: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const retry = useMutation({
    mutationFn: () => invoicesApi.archive(inv.id),
    onSuccess: (updated) => qc.setQueryData(['invoice', inv.id], updated),
    onError: (err) => toast.error('Could not file the invoice', errorMessage(err)),
  });

  // While filing is in progress, refresh the invoice every few seconds.
  useEffect(() => {
    if (inv.archive_status !== 'QUEUED') return undefined;
    const t = window.setInterval(() => void qc.invalidateQueries({ queryKey: ['invoice', inv.id] }), 4000);
    return () => window.clearInterval(t);
  }, [inv.archive_status, inv.id, qc]);

  if (!inv.archive_status) return null;
  if (inv.archive_status === 'ARCHIVED') {
    return inv.archive_url ? (
      <a href={inv.archive_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 py-1 text-sm font-medium text-brand-700 hover:underline">
        <Archive className="h-4 w-4" aria-hidden /> Filed in the document archive <ExternalLink className="h-3.5 w-3.5" aria-label="(opens in a new tab)" />
      </a>
    ) : (
      <span className="inline-flex items-center gap-1.5 text-sm text-gray-600"><Archive className="h-4 w-4" aria-hidden /> Filed in the document archive</span>
    );
  }
  if (inv.archive_status === 'QUEUED') {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm text-gray-600" role="status">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Filing in the document archive…
      </span>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-2 text-sm text-red-700" role="status">
      Not filed in the document archive{inv.archive_error ? `: ${inv.archive_error}` : '.'}
      {canRetry && (
        <button type="button" onClick={() => retry.mutate()} disabled={retry.isPending}
          className="inline-flex items-center gap-1 py-1 font-medium text-brand-700 hover:underline disabled:opacity-50">
          <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Try again
        </button>
      )}
    </span>
  );
}

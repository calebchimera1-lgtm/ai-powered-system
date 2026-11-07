import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { Camera, FileUp, ScanLine } from 'lucide-react';
import { useRef, useState, type DragEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { invoicesApi, type InvoiceSummary } from '@/api/invoices';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { DataTable, Pagination, type Column } from '@/components/ui/DataTable';
import { errorMessage } from '@/lib/errors';
import { formatDate, formatDateTime, formatKES } from '@/lib/format';

import { STATUS_LABEL, STATUS_TONE, isWorking } from './review';

const MAX_MB = 10;
const ACCEPT = 'image/jpeg,image/png,image/webp,application/pdf';

/** Client-side pre-check only; the server checks the real file contents again. */
export function checkFile(f: File): string | null {
  if (!ACCEPT.split(',').includes(f.type)) return 'Choose a photo (JPEG, PNG, WebP) or a PDF.';
  if (f.size > MAX_MB * 1024 * 1024) return `The file is larger than ${MAX_MB} MB.`;
  if (f.size === 0) return 'The file is empty.';
  return null;
}

const FILTERS = [
  { value: 'OPEN', label: 'To do' },
  { value: 'APPROVED', label: 'Approved' },
  { value: 'REJECTED', label: 'Rejected' },
  { value: '', label: 'All' },
];

export function InvoicesPage() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [status, setStatus] = useState('OPEN');
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const canUpload = can(PERM.INVOICES_UPLOAD);

  const list = useQuery({
    queryKey: ['invoices', { status, page }],
    queryFn: () => invoicesApi.list({ status, page, page_size: 25 }),
    placeholderData: keepPreviousData,
    // Keep the list fresh while anything is still being read.
    refetchInterval: (q) => (q.state.data?.items.some((i) => isWorking(i.status)) ? 2000 : false),
  });
  const stats = useQuery({ queryKey: ['invoices', 'stats'], queryFn: invoicesApi.stats });

  const send = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    const problem = checkFile(file);
    if (problem) return setError(problem);
    setProgress(0);
    try {
      const inv = await invoicesApi.upload(file, setProgress);
      void qc.invalidateQueries({ queryKey: ['invoices'] });
      navigate(`/purchasing/invoices/${inv.id}`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setProgress(null);
      if (fileRef.current) fileRef.current.value = '';
      if (cameraRef.current) cameraRef.current.value = '';
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    void send(e.dataTransfer.files[0]);
  };

  const columns: Column<InvoiceSummary>[] = [
    {
      key: 'f', header: 'Invoice',
      render: (i) => (
        <Link to={`/purchasing/invoices/${i.id}`} className="font-medium text-gray-900 hover:text-brand-700">
          {i.invoice_number ?? <span className="text-gray-500">No number yet</span>}
          <span className="block max-w-[14rem] truncate text-xs font-normal text-gray-500">{i.original_filename}</span>
        </Link>
      ),
    },
    { key: 's', header: 'Supplier', render: (i) => i.supplier?.name ?? <span className="text-gray-500">{i.extracted_supplier_name ?? 'Unknown'}</span> },
    { key: 'd', header: 'Invoice date', hideOnMobile: true, render: (i) => (i.invoice_date ? formatDate(i.invoice_date) : '—') },
    { key: 'u', header: 'Uploaded', hideOnMobile: true, render: (i) => <span className="whitespace-nowrap text-xs">{formatDateTime(i.created_at)}<span className="block text-gray-500">{i.uploaded_by.full_name}</span></span> },
    {
      key: 'st', header: 'Status',
      render: (i) => (
        <span className="flex flex-wrap items-center gap-1">
          <Badge tone={STATUS_TONE[i.status]}>{STATUS_LABEL[i.status]}</Badge>
          {i.status === 'NEEDS_REVIEW' && i.warnings > 0 && <span className="text-xs text-amber-700">{i.warnings} to check</span>}
        </span>
      ),
    },
    { key: 't', header: 'Total', className: 'text-right', render: (i) => <span className="whitespace-nowrap tabular-nums">{i.grand_total ? formatKES(i.grand_total) : '—'}</span> },
  ];

  const s = stats.data;
  const waiting = (s?.by_status.NEEDS_REVIEW ?? 0) + (s?.by_status.FAILED ?? 0);
  return (
    <>
      <PageHeader
        title="Scan invoices"
        description="Photograph or upload a supplier invoice. The system reads it and fills in a delivery for you to check; nothing reaches stock until someone approves it."
      />

      {canUpload && (
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={clsx('mb-6 rounded-xl border-2 border-dashed bg-white p-6 text-center transition-colors', dragging ? 'border-brand-500 bg-brand-50' : 'border-gray-300')}
        >
          <ScanLine className="mx-auto h-10 w-10 text-brand-600" aria-hidden />
          <p className="mt-2 text-sm font-medium text-gray-900">Drop an invoice here, take a photo or choose a file</p>
          <p className="mt-1 text-xs text-gray-500">JPEG, PNG, WebP or PDF up to {MAX_MB} MB. Lay the invoice flat, in good light, with all four corners showing.</p>
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            <Button icon={<Camera className="h-4 w-4" />} onClick={() => cameraRef.current?.click()} loading={progress !== null} className="sm:hidden">Take photo</Button>
            <Button variant="secondary" icon={<FileUp className="h-4 w-4" />} onClick={() => fileRef.current?.click()} loading={progress !== null}>Choose file</Button>
          </div>
          <input ref={fileRef} type="file" accept={ACCEPT} className="sr-only" aria-label="Invoice file" onChange={(e) => void send(e.target.files?.[0])} />
          <input ref={cameraRef} type="file" accept="image/*" capture="environment" className="sr-only" aria-label="Take a photo of the invoice" tabIndex={-1} onChange={(e) => void send(e.target.files?.[0])} />
          {progress !== null && (
            <div className="mx-auto mt-4 max-w-xs" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100} aria-label="Upload progress">
              <div className="h-2 overflow-hidden rounded-full bg-gray-100"><div className="h-full bg-brand-600 transition-all" style={{ width: `${progress}%` }} /></div>
              <p className="mt-1 text-xs text-gray-500">Uploading… {progress}%</p>
            </div>
          )}
          {error && <div className="mx-auto mt-4 max-w-md text-left"><Alert tone="error">{error}</Alert></div>}
        </div>
      )}

      {s && (
        <div className="mb-4 flex flex-wrap gap-x-6 gap-y-1 text-sm text-gray-600">
          <span><strong className="tabular-nums text-gray-900">{waiting}</strong> waiting for review</span>
          {s.waiting_over_24h > 0 && <span className="text-amber-700"><strong className="tabular-nums">{s.waiting_over_24h}</strong> waiting over 24 hours</span>}
          <span><strong className="tabular-nums text-gray-900">{s.approved}</strong> approved</span>
          {s.line_correction_rate !== null && (
            <span title="Share of lines on approved invoices that a reviewer had to correct: the real-world error rate of the reader.">
              <strong className="tabular-nums text-gray-900">{(s.line_correction_rate * 100).toFixed(1)}%</strong> of lines needed a correction
            </span>
          )}
        </div>
      )}

      <Card bodyClassName="p-0">
        <div className="flex flex-wrap gap-1 border-b border-gray-100 p-3" role="tablist" aria-label="Filter invoices">
          {FILTERS.map((f) => (
            <button key={f.label} role="tab" aria-selected={status === f.value} onClick={() => { setStatus(f.value); setPage(1); }}
              className={clsx('rounded-lg px-3 py-1.5 text-sm font-medium', status === f.value ? 'bg-brand-50 text-brand-700' : 'text-gray-600 hover:bg-gray-50')}>
              {f.label}
            </button>
          ))}
        </div>
        {list.isError ? <div className="p-4"><Alert tone="error">{errorMessage(list.error)}</Alert></div> : (
          <DataTable caption="Scanned invoices" columns={columns} rows={list.data?.items ?? []} rowKey={(i) => i.id} loading={list.isFetching && !list.data}
            emptyTitle={status === 'OPEN' ? 'Nothing waiting' : 'No invoices'} emptyDescription={status === 'OPEN' && canUpload ? 'Upload an invoice above to get started.' : undefined} />
        )}
        {list.data && list.data.total > 0 && <Pagination page={list.data.page} pages={list.data.pages} total={list.data.total} pageSize={list.data.page_size} onPageChange={setPage} />}
      </Card>
    </>
  );
}

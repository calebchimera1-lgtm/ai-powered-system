import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { FileSpreadsheet, FileText, Table } from 'lucide-react';
import { useState } from 'react';

import { reportsApi, type ReportType } from '@/api/analytics';
import { Alert } from '@/components/ui/Alert';
import { Card, PageHeader } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { rangeFor, type Preset } from '@/features/dashboard/DashboardPage';
import { useCategories } from '@/features/products/hooks';
import { errorMessage } from '@/lib/errors';
import { formatDate } from '@/lib/format';

const FORMATS = [
  { value: 'pdf', label: 'PDF', icon: FileText, hint: 'to print or share' },
  { value: 'xlsx', label: 'Excel', icon: FileSpreadsheet, hint: 'to work with the numbers' },
  { value: 'csv', label: 'CSV', icon: Table, hint: 'for other systems' },
] as const;

const PERIODS: { value: Preset; label: string }[] = [
  { value: '7', label: 'Last 7 days' },
  { value: '30', label: 'Last 30 days' },
  { value: 'month', label: 'This month' },
  { value: '90', label: 'Last 90 days' },
  { value: 'custom', label: 'Custom dates' },
];

export function ReportsPage() {
  const list = useQuery({ queryKey: ['reports'], queryFn: reportsApi.list });
  const cats = useCategories();
  const [preset, setPreset] = useState<Preset>('30');
  const [custom, setCustom] = useState(rangeFor('30'));
  const [category, setCategory] = useState('');
  const range = preset === 'custom' ? custom : rangeFor(preset);

  return (
    <>
      <PageHeader title="Reports" description="Download reports as PDF, Excel or CSV. Choose the period and, if you like, one category." />
      <div className="mb-5 flex flex-wrap items-end gap-3 rounded-xl border border-gray-200 bg-white p-4 shadow-card" role="group" aria-label="Report options">
        <label className="text-sm font-medium text-gray-700">Period
          <select value={preset} onChange={(e) => setPreset(e.target.value as Preset)} className="mt-1 block h-10 rounded-lg border border-gray-300 bg-white px-2 text-sm">
            {PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </label>
        {preset === 'custom' && (
          <>
            <label className="text-sm font-medium text-gray-700">From
              <input type="date" value={custom.from} max={custom.to} onChange={(e) => setCustom((c) => ({ ...c, from: e.target.value }))} className="mt-1 block h-10 rounded-lg border border-gray-300 px-2 text-sm" />
            </label>
            <label className="text-sm font-medium text-gray-700">To
              <input type="date" value={custom.to} min={custom.from} onChange={(e) => setCustom((c) => ({ ...c, to: e.target.value }))} className="mt-1 block h-10 rounded-lg border border-gray-300 px-2 text-sm" />
            </label>
          </>
        )}
        <label className="text-sm font-medium text-gray-700">Category
          <select value={category} onChange={(e) => setCategory(e.target.value)} className="mt-1 block h-10 rounded-lg border border-gray-300 bg-white px-2 text-sm">
            <option value="">All categories</option>
            {cats.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <p className="pb-2 text-sm text-gray-500">{formatDate(range.from)} to {formatDate(range.to)}</p>
      </div>

      {list.isLoading && <div className="flex justify-center py-12"><Spinner label="Loading…" /></div>}
      {list.isError && <Alert tone="error">{errorMessage(list.error)}</Alert>}
      {list.data?.length === 0 && <Card><EmptyState title="No reports available" description="Your role does not include any reports." /></Card>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {list.data?.map((r) => (
          <ReportCard key={r.key} report={r} range={range} categoryId={category ? Number(category) : null} />
        ))}
      </div>
    </>
  );
}

function ReportCard({ report, range, categoryId }: { report: ReportType; range: { from: string; to: string }; categoryId: number | null }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const get = async (format: string) => {
    setBusy(format);
    try {
      const name = await reportsApi.download(report.key, {
        format, category_id: categoryId,
        ...(report.uses_period ? { date_from: range.from, date_to: range.to } : {}),
      });
      toast.success('Report downloaded', name);
    } catch (e) {
      toast.error(`Could not create “${report.title}”`, errorMessage(e));
    } finally {
      setBusy(null);
    }
  };
  return (
    <Card title={report.title} description={report.description}>
      <p className="mb-3 text-xs text-gray-500">{report.uses_period ? 'Uses the period chosen above.' : 'As it stands now (the period does not apply).'}</p>
      <div className="flex flex-wrap gap-2">
        {FORMATS.filter((f) => report.formats.includes(f.value)).map((f) => (
          <button key={f.value} type="button" onClick={() => void get(f.value)} disabled={busy !== null}
            aria-label={`Download ${report.title} as ${f.label}`} title={`${f.label}: ${f.hint}`}
            className={clsx('inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-sm font-medium',
              'border-gray-300 bg-white text-gray-700 hover:border-brand-400 hover:bg-brand-50 disabled:opacity-60')}>
            {busy === f.value ? <Spinner label="" className="h-4 w-4" /> : <f.icon className="h-4 w-4" aria-hidden />}
            {f.label}
          </button>
        ))}
      </div>
    </Card>
  );
}

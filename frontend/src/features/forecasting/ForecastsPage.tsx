import { useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw, ShoppingCart, TrendingUp } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { forecastsApi, type ProductForecast } from '@/api/analytics';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { EmptyState } from '@/components/ui/EmptyState';
import { Spinner } from '@/components/ui/Spinner';
import { errorMessage } from '@/lib/errors';
import { formatDate, formatDateTime } from '@/lib/format';

import { PATTERN_LABEL, daysUntil, fmtQty, stockoutTone } from './labels';

export function ForecastsPage() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ['forecasts'],
    queryFn: forecastsApi.overview,
    refetchInterval: (query) => (query.state.data?.running ? 3000 : false),
  });

  const runNow = async () => {
    setError(null);
    try {
      await forecastsApi.run();
      await qc.invalidateQueries({ queryKey: ['forecasts'] });
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  if (q.isLoading) return <div className="flex justify-center py-20"><Spinner label="Loading forecasts…" /></div>;
  if (q.isError || !q.data) return <Alert tone="error">{errorMessage(q.error)}</Alert>;
  const { run, running, products } = q.data;
  const s = run?.summary ?? {};
  const toOrder = products.filter((p) => p.should_order);
  const soon = products.filter((p) => p.stockout_date && daysUntil(p.stockout_date) <= p.lead_time_days);
  const canRun = can(PERM.PURCHASES_WRITE);

  const columns: Column<ProductForecast>[] = [
    {
      key: 'p', header: 'Product',
      render: (p) => (
        <Link to={`/forecasts/${p.product.id}`} className="font-medium text-gray-900 hover:text-brand-700">
          {p.product.name}
          <span className="block text-xs font-normal text-gray-500">
            {p.abc_class && `Class ${p.abc_class} · `}{PATTERN_LABEL[p.demand_pattern ?? ''] ?? p.demand_pattern}
            {p.low_confidence && ' · low confidence'}
          </span>
        </Link>
      ),
    },
    { key: 'n7', header: 'Next 7 days', className: 'text-right', render: (p) => <span className="tabular-nums">{fmtQty(p.next_7_days)}</span> },
    { key: 'oh', header: 'In stock', className: 'text-right', hideOnMobile: true, render: (p) => <span className="tabular-nums">{fmtQty(Number(p.on_hand))}{Number(p.on_order) > 0 && <span className="block text-xs text-gray-500">+{fmtQty(Number(p.on_order))} ordered</span>}</span> },
    {
      key: 'so', header: 'Runs out', render: (p) => {
        if (!p.stockout_date) return <span className="text-gray-500">Not within 4 weeks</span>;
        const tone = stockoutTone(p);
        return <Badge tone={tone}>{formatDate(p.stockout_date)}{p.days_of_cover !== null && ` · ${fmtQty(p.days_of_cover)} ${p.days_of_cover === 1 ? 'day' : 'days'}`}</Badge>;
      },
    },
    { key: 'r', header: 'Suggested order', className: 'text-right', render: (p) => (p.should_order ? <span className="font-medium tabular-nums text-gray-900">{fmtQty(Number(p.suggested_quantity))} {p.product.unit_of_measure}</span> : <span className="text-gray-400">—</span>) },
    { key: 'm', header: 'Model', hideOnMobile: true, render: (p) => <span className="text-xs text-gray-600">{p.model_label}</span> },
  ];

  return (
    <>
      <PageHeader title="Demand forecast" description="Expected sales for the next 4 weeks, when each product will run out, and what to reorder."
        actions={<>
          {can(PERM.PURCHASES_WRITE) && toOrder.length > 0 && <Link to="/reorder"><Button variant="secondary" icon={<ShoppingCart className="h-4 w-4" />}>Reorder suggestions ({toOrder.length})</Button></Link>}
          {canRun && <Button icon={<RefreshCw className="h-4 w-4" />} onClick={runNow} loading={running}>{running ? 'Updating…' : 'Update forecast'}</Button>}
        </>} />
      {error && <div className="mb-4"><Alert tone="error">{error}</Alert></div>}
      {!run ? (
        <Card>
          <EmptyState icon={<TrendingUp className="h-6 w-6" aria-hidden />} title={running ? 'Preparing the first forecast…' : 'No forecast yet'}
            description={running ? 'Learning from past sales. This takes up to a minute.' : 'Forecasts are made every night from sales history. You can also start one now.'} />
        </Card>
      ) : (
        <>
          <div className="mb-4 grid gap-3 sm:grid-cols-3">
            <Summary label="Need ordering now" value={String(toOrder.length)} hint={toOrder.length ? 'Below the reorder point' : 'Nothing below its reorder point'} />
            <Summary label="May run out before a delivery" value={String(soon.length)} hint="Forecast stock-out within the supplier lead time" />
            <Summary label="Better than the simple baseline" value={s.compared_with_seasonal_naive ? `${s.beats_seasonal_naive} of ${s.compared_with_seasonal_naive}` : '—'}
              hint="Products whose chosen model beat “same weekday last week” in backtesting" />
          </div>
          <Card bodyClassName="p-0">
            <DataTable caption="Product forecasts" columns={columns} rows={products} rowKey={(p) => p.product.id} emptyTitle="No products with sales yet" />
            <p className="border-t border-gray-100 px-4 py-2.5 text-xs text-gray-500">
              Updated {formatDateTime(run.finished_at)} from sales {run.history_start && formatDate(run.history_start)} to {run.history_end && formatDate(run.history_end)}.
              Each product uses the model that forecast its own past sales best.
            </p>
          </Card>
        </>
      )}
    </>
  );
}

function Summary({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-card">
      <p className="text-sm text-gray-600">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-gray-900">{value}</p>
      <p className="mt-1 text-xs text-gray-500">{hint}</p>
    </div>
  );
}

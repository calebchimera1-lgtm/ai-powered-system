import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { ArrowLeft } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';

import { forecastsApi, type ModelScore, type ProductForecast } from '@/api/analytics';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Card, PageHeader } from '@/components/ui/Card';
import { Spinner } from '@/components/ui/Spinner';
import { errorMessage } from '@/lib/errors';
import { formatDate } from '@/lib/format';

import { ForecastChart } from './ForecastChart';
import { PATTERN_LABEL, WEEKDAYS, fmtQty, stockoutTone } from './labels';

const n2 = (v: number | null | undefined) => (v === null || v === undefined ? '—' : v.toFixed(2));

export function ForecastDetailPage() {
  const id = Number(useParams().productId);
  const q = useQuery({ queryKey: ['forecasts', 'product', id], queryFn: () => forecastsApi.product(id) });
  if (q.isLoading) return <div className="flex justify-center py-20"><Spinner label="Loading…" /></div>;
  if (q.isError || !q.data) return <Alert tone="error">{errorMessage(q.error)}</Alert>;
  const { forecast: f, scores, series, run } = q.data;
  const unit = f.product.unit_of_measure;
  const today = series.find((p) => p.forecast !== null && p.forecast !== undefined)?.date ?? '';

  return (
    <>
      <PageHeader title={f.product.name} description={`${f.product.sku} · forecast made ${formatDate(run.finished_at)}`}
        actions={<Link to="/forecasts" className="inline-flex items-center gap-1 text-sm font-medium text-gray-600 hover:text-gray-900"><ArrowLeft className="h-4 w-4" />All forecasts</Link>} />
      {f.low_confidence && <div className="mb-4"><Alert tone="warning">Only {f.history_days} days of sales so far: this is a rough forecast from a simple model. It improves as more sales are recorded.</Alert></div>}
      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Daily sales and forecast" className="xl:col-span-2">
          <ForecastChart series={series} today={today} unit={unit} />
          <p className="mt-3 text-xs text-gray-500">The shaded range shows where 8 days out of 10 should fall, based on how far this model's forecasts have been off in the past.</p>
        </Card>
        <Reorder f={f} />
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Profile f={f} />
        <Models scores={scores} chosen={f.model_name} />
      </div>
    </>
  );
}

function Row({ label, value, strong }: { label: string; value: React.ReactNode; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5">
      <dt className="text-sm text-gray-600">{label}</dt>
      <dd className={clsx('text-right text-sm tabular-nums', strong ? 'font-semibold text-gray-900' : 'text-gray-900')}>{value}</dd>
    </div>
  );
}

function Reorder({ f }: { f: ProductForecast }) {
  const unit = f.product.unit_of_measure;
  const ltd = f.reorder_point - f.safety_stock;
  return (
    <Card title="Stock and reordering">
      <dl className="divide-y divide-gray-100">
        <Row label="In stock now" value={`${fmtQty(Number(f.on_hand))} ${unit}`} />
        {Number(f.on_order) > 0 && <Row label="Already on order" value={`${fmtQty(Number(f.on_order))} ${unit}`} />}
        <Row label="Expected sales, next 7 days" value={`${fmtQty(f.next_7_days)} ${unit}`} />
        <Row label="Expected to run out" value={f.stockout_date ? <Badge tone={stockoutTone(f)}>{formatDate(f.stockout_date)}</Badge> : 'Not within 4 weeks'} />
        <Row label={`Sales during the ${f.lead_time_days}-day delivery time`} value={`${fmtQty(Math.max(ltd, 0))} ${unit}`} />
        <Row label="Safety stock (95% service level)" value={`${fmtQty(f.safety_stock)} ${unit}`} />
        <Row label="Reorder point" value={`${fmtQty(f.reorder_point)} ${unit}`} strong />
      </dl>
      <div className={clsx('mt-3 rounded-lg p-3 text-sm', f.should_order ? 'bg-amber-50 text-amber-900' : 'bg-gray-50 text-gray-700')}>
        {f.should_order
          ? <>Order <strong>{fmtQty(Number(f.suggested_quantity))} {unit}</strong> now: stock plus open orders are at or below the reorder point.</>
          : 'No order needed yet: stock plus open orders are above the reorder point.'}
      </div>
    </Card>
  );
}

function Profile({ f }: { f: ProductForecast }) {
  const prof = f.weekday_profile ?? [];
  const max = Math.max(...prof, 1);
  return (
    <Card title="Sales pattern" description="Last 13 weeks; 1.00 = an average day">
      {/* Single series, so no legend: the title names it. Values are printed, so the bars are not the only way to read them. */}
      <ul className="space-y-1.5" aria-label="Sales by weekday relative to an average day">
        {prof.map((v, i) => (
          <li key={i} className="flex items-center gap-3 text-sm">
            <span className="w-9 text-gray-600">{WEEKDAYS[i]}</span>
            <span className="h-3 flex-1 rounded-r bg-gray-100">
              <span className="block h-3 rounded-r" style={{ width: `${(v / max) * 100}%`, background: '#2a78d6' }} title={`${WEEKDAYS[i]}: ${v.toFixed(2)}`} />
            </span>
            <span className="w-10 text-right tabular-nums text-gray-900">{v.toFixed(2)}</span>
          </li>
        ))}
      </ul>
      <dl className="mt-4 divide-y divide-gray-100 border-t border-gray-100">
        <Row label="Demand type" value={PATTERN_LABEL[f.demand_pattern ?? ''] ?? '—'} />
        <Row label="Month-end payday (28th–2nd)" value={f.payday_effect ? `${f.payday_effect >= 1 ? '+' : ''}${Math.round((f.payday_effect - 1) * 100)}% vs other days` : '—'} />
        <Row label="Average per day (last 4 weeks)" value={`${fmtQty(f.avg_daily_28)} ${f.product.unit_of_measure}`} />
        <Row label="Revenue class (90 days)" value={f.abc_class ? `${f.abc_class} ${f.abc_class === 'A' ? '(top 80% of revenue)' : f.abc_class === 'B' ? '(next 15%)' : '(last 5%)'}` : '—'} />
      </dl>
    </Card>
  );
}

function Models({ scores, chosen }: { scores: ModelScore[]; chosen: string }) {
  const sorted = [...scores].sort((a, b) => (a.rmsse ?? 99) - (b.rmsse ?? 99));
  return (
    <Card title="How the model was chosen" description="Each model forecast this product's past weeks without seeing them; the lowest RMSSE wins. Below 1.00 beats “same weekday last week”." bodyClassName="p-0">
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
            <tr><th className="px-4 py-2">Model</th><th className="px-3 py-2 text-right">Avg error / day</th><th className="px-3 py-2 text-right">MASE</th><th className="px-3 py-2 text-right">RMSSE</th></tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {sorted.map((s) => (
              <tr key={s.model} className={s.model === chosen ? 'bg-brand-50/60' : undefined}>
                <td className="px-4 py-2">{s.label}{s.model === chosen && <span className="ml-2"><Badge tone="green">Chosen</Badge></span>}</td>
                <td className="px-3 py-2 text-right tabular-nums">{n2(s.mae)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{n2(s.mase)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{n2(s.rmsse)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sorted[0] && <p className="px-4 py-2.5 text-xs text-gray-500">Backtested over {sorted[0].origins} past weeks.</p>}
    </Card>
  );
}

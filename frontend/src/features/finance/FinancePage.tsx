import { useQuery } from '@tanstack/react-query';
import { Coins, Info, PackageMinus, Receipt, TrendingUp, Wallet } from 'lucide-react';
import { useState } from 'react';

import { financeApi } from '@/api/finance';
import { Alert } from '@/components/ui/Alert';
import { Card, PageHeader } from '@/components/ui/Card';
import { DataTable } from '@/components/ui/DataTable';
import { Spinner } from '@/components/ui/Spinner';
import { StatCard } from '@/components/ui/StatCard';
import { todayISO } from '@/features/sales/SalesPage';
import { errorMessage } from '@/lib/errors';
import { formatKES, formatPercent, formatQty, num } from '@/lib/format';

import { RevenueChart } from './RevenueChart';

function shift(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

const PRESETS = [
  { key: 'today', label: 'Today', range: (t: string): [string, string] => [t, t] },
  { key: '7', label: '7 days', range: (t: string): [string, string] => [shift(t, -6), t] },
  { key: '30', label: '30 days', range: (t: string): [string, string] => [shift(t, -29), t] },
  { key: 'month', label: 'This month', range: (t: string): [string, string] => [`${t.slice(0, 8)}01`, t] },
];

const control = 'h-10 rounded-lg border border-gray-300 bg-white px-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30';

export function FinancePage() {
  const today = todayISO();
  const [preset, setPreset] = useState<string>('30');
  const [from, setFrom] = useState(shift(today, -29));
  const [to, setTo] = useState(today);
  const q = useQuery({ queryKey: ['analytics', { from, to }], queryFn: () => financeApi.overview({ date_from: from, date_to: to }) });
  const s = q.data?.summary;
  const METHOD: Record<string, string> = { CASH: 'Cash', MPESA: 'M-Pesa', CARD: 'Card' };
  const payTotal = (q.data?.payment_methods ?? []).reduce((a, p) => a + num(p.total), 0);

  return (
    <>
      <PageHeader title="Profit and sales" description="Revenue excludes VAT. Costs use each product's weighted average cost at the moment of sale." />
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div role="group" aria-label="Period" className="flex flex-wrap gap-1 rounded-lg bg-gray-100 p-1">
          {PRESETS.map((p) => (
            <button key={p.key} type="button" aria-pressed={preset === p.key} onClick={() => { const [a, b] = p.range(today); setPreset(p.key); setFrom(a); setTo(b); }}
              className={`rounded-md px-3 py-1.5 text-sm font-medium ${preset === p.key ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-600 hover:text-gray-900'}`}>{p.label}</button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-2 sm:flex">
          <input type="date" aria-label="From" value={from} max={to} onChange={(e) => { setPreset(''); setFrom(e.target.value); }} className={control} />
          <input type="date" aria-label="To" value={to} min={from} onChange={(e) => { setPreset(''); setTo(e.target.value); }} className={control} />
        </div>
      </div>

      {q.isLoading && <div className="flex justify-center py-20"><Spinner label="Calculating…" /></div>}
      {q.isError && <Alert tone="error">{errorMessage(q.error)}</Alert>}
      {s && q.data && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2 lg:grid-cols-3">
            <StatCard label="Revenue" value={formatKES(s.revenue)} icon={Coins} tone="blue" hint={`${s.transactions} sales · VAT ${formatKES(s.vat_collected)}`} />
            <StatCard label="Cost of goods sold" value={formatKES(s.cost_of_goods_sold)} icon={Receipt} tone="gray" />
            <StatCard label="Gross profit" value={formatKES(s.gross_profit)} icon={TrendingUp} tone="green" hint={`Margin ${formatPercent(s.gross_margin_percent)}`} />
            <StatCard label="Stock losses" value={formatKES(s.stock_losses)} icon={PackageMinus} tone="amber" hint={`Adjustments ${formatKES(s.net_adjustments)}`} />
            <StatCard label="Expenses" value={formatKES(s.operating_expenses)} icon={Wallet} tone="gray" />
            <StatCard label="Net profit (estimate)" value={formatKES(s.net_profit_estimate)} icon={TrendingUp} tone={num(s.net_profit_estimate) >= 0 ? 'green' : 'red'} />
          </div>

          <Card title="Daily revenue and gross profit">
            {q.data.daily.some((d) => num(d.revenue) !== 0) ? <RevenueChart data={q.data.daily} /> : <p className="py-10 text-center text-sm text-gray-500">No sales in this period.</p>}
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="By category" bodyClassName="p-0">
              <DataTable
                columns={[
                  { key: 'c', header: 'Category', render: (r) => <span className="font-medium text-gray-900">{r.category}</span> },
                  { key: 'r', header: 'Revenue', className: 'text-right', render: (r) => <span className="whitespace-nowrap tabular-nums">{formatKES(r.revenue)}</span> },
                  { key: 'p', header: 'Gross profit', className: 'text-right', render: (r) => <span className="whitespace-nowrap tabular-nums">{formatKES(r.gross_profit)}</span> },
                  { key: 'm', header: 'Margin', className: 'text-right', render: (r) => <span className="tabular-nums">{formatPercent(r.margin_percent)}</span> },
                ]}
                rows={q.data.by_category}
                rowKey={(r) => r.category}
                emptyTitle="No sales in this period"
              />
            </Card>
            <Card title="Most profitable products" bodyClassName="p-0">
              <DataTable
                columns={[
                  { key: 'n', header: 'Product', render: (r) => <span className="font-medium text-gray-900">{r.name}<span className="block text-xs font-normal text-gray-500">{formatQty(r.quantity)} sold</span></span> },
                  { key: 'r', header: 'Revenue', className: 'text-right', hideOnMobile: true, render: (r) => <span className="whitespace-nowrap tabular-nums">{formatKES(r.revenue)}</span> },
                  { key: 'p', header: 'Gross profit', className: 'text-right', render: (r) => <span className="whitespace-nowrap tabular-nums">{formatKES(r.gross_profit)}</span> },
                  { key: 'm', header: 'Margin', className: 'text-right', render: (r) => <span className="tabular-nums">{formatPercent(r.margin_percent)}</span> },
                ]}
                rows={q.data.top_products}
                rowKey={(r) => r.product_id}
                emptyTitle="No sales in this period"
              />
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card title="How customers paid">
              <ul className="space-y-3">
                {q.data.payment_methods.map((p) => {
                  const share = payTotal > 0 ? (num(p.total) / payTotal) * 100 : 0;
                  return (
                    <li key={p.payment_method}>
                      <div className="flex justify-between text-sm"><span className="font-medium text-gray-800">{METHOD[p.payment_method]}</span><span className="tabular-nums text-gray-900">{formatKES(p.total)}</span></div>
                      <div className="mt-1 h-2 rounded-full bg-gray-100"><div className="h-2 rounded-full bg-brand-600" style={{ width: `${share}%` }} /></div>
                      <p className="mt-0.5 text-xs text-gray-500">{p.transactions} sales · {share.toFixed(0)}%</p>
                    </li>
                  );
                })}
                {q.data.payment_methods.length === 0 && <li className="text-sm text-gray-500">No sales in this period.</li>}
              </ul>
            </Card>
            <Card title="Other figures" className="lg:col-span-2">
              <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
                <div className="flex justify-between"><dt className="text-gray-500">Customers paid (incl. VAT)</dt><dd className="tabular-nums">{formatKES(s.sales_gross)}</dd></div>
                <div className="flex justify-between"><dt className="text-gray-500">Refunds (incl. VAT)</dt><dd className="tabular-nums">{formatKES(s.refunds_gross)}</dd></div>
                <div className="flex justify-between"><dt className="text-gray-500">Discounts given</dt><dd className="tabular-nums">{formatKES(s.discounts_given)}</dd></div>
                <div className="flex justify-between"><dt className="text-gray-500">Average sale</dt><dd className="tabular-nums">{formatKES(s.average_basket)}</dd></div>
                <div className="flex justify-between"><dt className="text-gray-500">Items sold</dt><dd className="tabular-nums">{formatQty(s.items_sold)}</dd></div>
                <div className="flex justify-between"><dt className="text-gray-500">Stock purchased (incl. VAT)</dt><dd className="tabular-nums">{formatKES(s.purchases_total)}</dd></div>
              </dl>
              <p className="mt-4 flex gap-2 rounded-lg bg-gray-50 p-3 text-xs text-gray-600">
                <Info className="mt-0.5 h-4 w-4 shrink-0 text-gray-400" aria-hidden />
                Net profit estimate = gross profit − stock losses ± stock adjustments − operating expenses. It does not include tax on profit, loan interest or depreciation.
              </p>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}

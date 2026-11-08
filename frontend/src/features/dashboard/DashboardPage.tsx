import { keepPreviousData, useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { AlertTriangle, CalendarClock, ClipboardCheck, PackageX, ShieldAlert, TrendingDown } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { dashboardApi, type Dashboard, type Mover } from '@/api/analytics';
import { useAuth } from '@/auth/AuthProvider';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Card, PageHeader } from '@/components/ui/Card';
import { Spinner } from '@/components/ui/Spinner';
import { RevenueChart } from '@/features/finance/RevenueChart';
import { useCategories } from '@/features/products/hooks';
import { errorMessage } from '@/lib/errors';
import { formatDate, formatKES } from '@/lib/format';

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

export type Preset = '7' | '30' | 'month' | '90' | 'custom';

/** Date range for a preset, ending today (browser's calendar day). */
export function rangeFor(preset: Preset, now: Date = new Date()): { from: string; to: string } {
  const to = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (preset === 'month') return { from: iso(new Date(to.getFullYear(), to.getMonth(), 1)), to: iso(to) };
  const days = preset === '7' ? 7 : preset === '90' ? 90 : 30;
  const from = new Date(to);
  from.setDate(from.getDate() - (days - 1));
  return { from: iso(from), to: iso(to) };
}

const PRESETS: { value: Preset; label: string }[] = [
  { value: '7', label: '7 days' },
  { value: '30', label: '30 days' },
  { value: 'month', label: 'This month' },
  { value: '90', label: '90 days' },
  { value: 'custom', label: 'Custom' },
];

const qty = (v: string | number, unit?: string) =>
  `${Number(v).toLocaleString('en-KE', { maximumFractionDigits: 1 })}${unit ? ` ${unit}` : ''}`;

export function DashboardPage({ greeting }: { greeting: string }) {
  const { user } = useAuth();
  const [preset, setPreset] = useState<Preset>('30');
  const [custom, setCustom] = useState(rangeFor('30'));
  const [category, setCategory] = useState('');
  const range = preset === 'custom' ? custom : rangeFor(preset);
  const cats = useCategories();
  const q = useQuery({
    queryKey: ['dashboard', range, category],
    queryFn: () => dashboardApi.get({ date_from: range.from, date_to: range.to, category_id: category ? Number(category) : null }),
    placeholderData: keepPreviousData,
    enabled: range.from <= range.to,
  });
  const d = q.data;
  const catName = cats.data?.find((c) => String(c.id) === category)?.name;

  return (
    <>
      <PageHeader title={`${greeting}, ${user?.full_name.split(' ')[0] ?? ''}`}
        description={`Store overview${catName ? ` · ${catName}` : ''}: ${formatDate(range.from)} to ${formatDate(range.to)}`} />

      {/* Filters: one row above everything they control. */}
      <div className="mb-5 flex flex-wrap items-center gap-2" role="group" aria-label="Dashboard filters">
        <div className="flex flex-wrap rounded-lg border border-gray-200 bg-white p-0.5" role="radiogroup" aria-label="Period">
          {PRESETS.map((p) => (
            <button key={p.value} type="button" role="radio" aria-checked={preset === p.value} onClick={() => setPreset(p.value)}
              className={clsx('rounded-md px-3 py-1.5 text-sm font-medium', preset === p.value ? 'bg-brand-600 text-white' : 'text-gray-600 hover:bg-gray-50')}>
              {p.label}
            </button>
          ))}
        </div>
        {preset === 'custom' && (
          <span className="flex items-center gap-1.5 text-sm text-gray-600">
            <input type="date" aria-label="From" value={custom.from} max={custom.to} onChange={(e) => setCustom((c) => ({ ...c, from: e.target.value }))} className="h-9 rounded-lg border border-gray-300 px-2 text-sm" />
            to
            <input type="date" aria-label="To" value={custom.to} min={custom.from} onChange={(e) => setCustom((c) => ({ ...c, to: e.target.value }))} className="h-9 rounded-lg border border-gray-300 px-2 text-sm" />
          </span>
        )}
        <select aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value)} className="h-9 rounded-lg border border-gray-300 bg-white px-2 text-sm">
          <option value="">All categories</option>
          {cats.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        {q.isFetching && d && <Spinner label="" className="h-4 w-4" />}
      </div>

      {q.isError && <Alert tone="error">{errorMessage(q.error)}</Alert>}
      {!d && q.isLoading && <div className="flex justify-center py-20"><Spinner label="Loading dashboard…" /></div>}
      {d && <Body d={d} />}
    </>
  );
}

function Body({ d }: { d: Dashboard }) {
  const s = d.sales;
  const a = d.approvals;
  const pending = a.invoices_to_review + a.adjustments_pending + a.returns_pending + a.purchase_orders_draft;
  return (
    <div className="space-y-4">
      {s && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Kpi label="Today's sales" value={formatKES(s.today_revenue)} hint={`${s.today_transactions} sale${s.today_transactions === 1 ? '' : 's'} · excl. VAT`} />
          <Kpi label="Revenue (period)" value={formatKES(s.period_revenue)} hint={`This month so far: ${formatKES(s.month_revenue)}`} />
          <Kpi label="Gross profit (period)" value={formatKES(s.period_gross_profit)} hint={s.gross_margin_percent !== null ? `${Number(s.gross_margin_percent).toFixed(1)}% margin` : 'No sales in the period'} />
          <Kpi label="Inventory value" value={d.inventory.inventory_value !== null ? formatKES(d.inventory.inventory_value) : '—'} hint={`${d.inventory.total_products} products, at average cost`} />
        </div>
      )}

      {/* Things that need attention; each links to where it is handled. */}
      <div className={clsx('grid gap-3 sm:grid-cols-2', d.open_irregularities !== null ? 'xl:grid-cols-5' : 'xl:grid-cols-4')}>
        <Attention to="/products?stock=low" icon={<PackageX className="h-5 w-5" />} label="Low or out of stock" value={d.inventory.low_stock + d.inventory.out_of_stock}
          hint={d.inventory.out_of_stock ? `${d.inventory.out_of_stock} out of stock` : 'At or below minimum'} />
        <Attention to="/products?stock=expiring" icon={<CalendarClock className="h-5 w-5" />} label="Expiring soon" value={d.inventory.expiring_soon} hint="Products with a batch near expiry" />
        <Attention to="/reorder" icon={<TrendingDown className="h-5 w-5" />} label="Predicted shortages" value={d.shortages.length} hint="May run out before a delivery" />
        <Attention to={a.invoices_to_review ? '/purchasing/invoices' : a.adjustments_pending ? '/stock/adjustments' : a.returns_pending ? '/returns' : '/purchasing/orders'} icon={<ClipboardCheck className="h-5 w-5" />} label="Pending approvals" value={pending}
          hint={[a.invoices_to_review && `${a.invoices_to_review} invoices`, a.purchase_orders_draft && `${a.purchase_orders_draft} draft orders`, a.adjustments_pending && `${a.adjustments_pending} adjustments`, a.returns_pending && `${a.returns_pending} returns`].filter(Boolean).join(' · ') || 'Nothing waiting'} />
        {d.open_irregularities !== null && (
          <Attention to="/anomalies" icon={<ShieldAlert className="h-5 w-5" />} label="Irregularities to review" value={d.open_irregularities} hint="Medium or high severity" />
        )}
      </div>

      {s && (
        <div className="grid gap-4 xl:grid-cols-3">
          <Card title="Revenue and gross profit by day" className="xl:col-span-2">
            <RevenueChart data={s.trend} />
          </Card>
          {d.categories ? <Categories rows={d.categories} /> : <MoverCard title="Fast movers" rows={d.movers.fast} empty="No sales in the period" />}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {(!s || d.categories) && <MoverCard title="Fast movers" rows={d.movers.fast} empty="No sales in the period" />}
        <MoverCard title="Slow movers" rows={d.movers.slow} empty="—" slow />
        <ListCard title="Predicted shortages" link={{ to: '/reorder', label: 'Reorder suggestions' }} empty="No shortages predicted before the next delivery.">
          {d.shortages.map((x) => (
            <Line key={x.product_id} to={`/forecasts/${x.product_id}`} name={x.name}
              right={<Badge tone="red">{formatDate(x.stockout_date)}</Badge>}
              sub={`Delivery takes ${x.lead_time_days} day${x.lead_time_days === 1 ? '' : 's'} · order ${qty(x.suggested_quantity, x.unit)}`} />
          ))}
        </ListCard>
        <ListCard title="Low stock" link={{ to: '/products', label: 'Products' }} empty="Everything is above its minimum.">
          {d.inventory.low_stock_items.map((x) => (
            <Line key={x.product_id} to={`/products/${x.product_id}`} name={x.name} right={<span className="tabular-nums text-gray-900">{qty(x.on_hand, x.unit)}</span>} sub={`Minimum ${qty(x.min_stock, x.unit)}`} />
          ))}
        </ListCard>
        <ListCard title="Expiring soon" link={{ to: '/stock/movements', label: 'Stock' }} empty="No batches near expiry.">
          {d.inventory.expiring_items.map((x) => (
            <Line key={x.product_id} to={`/products/${x.product_id}`} name={x.name}
              right={<Badge tone={x.expired ? 'red' : 'amber'}>{x.expired ? 'Expired ' : ''}{formatDate(x.expiry_date)}</Badge>} sub={`${qty(x.quantity, x.unit)} in the batch`} />
          ))}
        </ListCard>
      </div>
    </div>
  );
}

function Kpi({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-card">
      <p className="text-sm text-gray-600">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-gray-900">{value}</p>
      <p className="mt-1 text-xs text-gray-500">{hint}</p>
    </div>
  );
}

function Attention({ to, icon, label, value, hint }: { to: string; icon: ReactNode; label: string; value: number; hint: string }) {
  const hot = value > 0;
  return (
    <Link to={to} className="group flex items-start gap-3 rounded-xl border border-gray-200 bg-white p-4 shadow-card hover:border-brand-300">
      <span className={clsx('rounded-lg p-2', hot ? 'bg-amber-50 text-amber-700' : 'bg-gray-100 text-gray-500')} aria-hidden>{icon}</span>
      <span className="min-w-0">
        <span className="block text-sm text-gray-600 group-hover:text-gray-900">{label}</span>
        <span className="mt-0.5 flex items-center gap-1.5 text-xl font-semibold tabular-nums text-gray-900">
          {value}{hot && <AlertTriangle className="h-4 w-4 text-amber-600" aria-label="needs attention" />}
        </span>
        <span className="mt-0.5 block text-xs text-gray-500">{hint}</span>
      </span>
    </Link>
  );
}

function Categories({ rows }: { rows: NonNullable<Dashboard['categories']> }) {
  const max = Math.max(...rows.map((r) => Number(r.revenue)), 1);
  return (
    <Card title="Revenue by category" description="Period total, excl. VAT">
      {rows.length === 0 ? <p className="text-sm text-gray-500">No sales in the period.</p> : (
        // Single series (revenue): one hue, values printed beside each bar.
        <ul className="space-y-3" aria-label="Revenue by category">
          {rows.map((r) => (
            <li key={r.category}>
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <span className="text-gray-700">{r.category}</span>
                <span className="tabular-nums text-gray-900">{formatKES(r.revenue)}</span>
              </div>
              <div className="mt-1 h-2.5 rounded-r bg-gray-100">
                <div className="h-2.5 rounded-r" style={{ width: `${(Number(r.revenue) / max) * 100}%`, background: '#2a78d6' }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function MoverCard({ title, rows, empty, slow }: { title: string; rows: Mover[]; empty: string; slow?: boolean }) {
  return (
    <ListCard title={title} link={{ to: '/forecasts', label: 'Forecasts' }} empty={empty}>
      {rows.map((m) => (
        <Line key={m.product_id} to={`/forecasts/${m.product_id}`} name={m.name}
          right={<span className="tabular-nums text-gray-900">{qty(m.per_day)}/day</span>}
          sub={slow
            ? `${qty(m.on_hand, m.unit)} in stock${m.days_of_cover !== null ? ` · ${qty(m.days_of_cover)} days of cover` : ' · no sales in the period'}`
            : `${qty(m.on_hand, m.unit)} in stock`} />
      ))}
    </ListCard>
  );
}

function ListCard({ title, link, empty, children }: { title: string; link: { to: string; label: string }; empty: string; children: ReactNode[] }) {
  return (
    <Card title={title} actions={<Link to={link.to} className="text-sm font-medium text-brand-700 hover:underline">{link.label}</Link>} bodyClassName="p-0">
      {children.length === 0 ? <p className="px-5 py-6 text-sm text-gray-500">{empty}</p> : <ul className="divide-y divide-gray-100">{children}</ul>}
    </Card>
  );
}

function Line({ to, name, sub, right }: { to: string; name: string; sub: string; right: ReactNode }) {
  return (
    <li>
      <Link to={to} className="flex items-center justify-between gap-3 px-4 py-2.5 hover:bg-gray-50 sm:px-5">
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium text-gray-900">{name}</span>
          <span className="block text-xs text-gray-500">{sub}</span>
        </span>
        <span className="shrink-0 text-sm">{right}</span>
      </Link>
    </li>
  );
}

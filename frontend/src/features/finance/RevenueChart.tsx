import { useState } from 'react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { formatKES } from '@/lib/format';

// Categorical slots 1 and 2 of the validated chart palette (light surface):
// blue = revenue, orange = gross profit. Validated: CVD dE 24.7, contrast >= 3:1.
export const SERIES = { revenue: '#2a78d6', profit: '#eb6834' } as const;

const dayLabel = (iso: string) =>
  new Intl.DateTimeFormat('en-KE', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(`${iso}T00:00:00Z`));

const compact = (n: number) => new Intl.NumberFormat('en-KE', { notation: 'compact', maximumFractionDigits: 1 }).format(n);

/** One day; `transactions` is optional (the dashboard trend does not carry it). */
export interface TrendDay { day: string; revenue: string | number; gross_profit: string | number; transactions?: number }
type Point = TrendDay;

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: Point }[] }) {
  if (!active || !payload?.length) return null;
  const p = payload[0]!.payload;
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 font-semibold text-gray-900">{dayLabel(p.day)}</p>
      <p className="flex items-center gap-2 text-gray-700"><span className="h-0.5 w-3" style={{ background: SERIES.revenue }} />Revenue <span className="ml-auto pl-3 tabular-nums text-gray-900">{formatKES(p.revenue)}</span></p>
      <p className="flex items-center gap-2 text-gray-700"><span className="h-0.5 w-3" style={{ background: SERIES.profit }} />Gross profit <span className="ml-auto pl-3 tabular-nums text-gray-900">{formatKES(p.gross_profit)}</span></p>
      {p.transactions !== undefined && <p className="mt-1 text-gray-500">{p.transactions} sale{p.transactions === 1 ? '' : 's'}</p>}
    </div>
  );
}

/** Daily revenue and gross profit: one KES axis, two thin lines, crosshair tooltip. */
export function RevenueChart({ data }: { data: TrendDay[] }) {
  const [asTable, setAsTable] = useState(false);
  const rows = data.map((d) => ({ ...d, revenue: Number(d.revenue), gross_profit: Number(d.gross_profit) }));
  const last = rows[rows.length - 1];
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <ul className="flex gap-4 text-xs text-gray-600" aria-label="Legend">
          <li className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded" style={{ background: SERIES.revenue }} />Revenue (excl. VAT)</li>
          <li className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded" style={{ background: SERIES.profit }} />Gross profit</li>
        </ul>
        <button type="button" onClick={() => setAsTable((v) => !v)} className="text-xs font-medium text-brand-700 hover:underline">
          {asTable ? 'Show chart' : 'Show as table'}
        </button>
      </div>
      {asTable ? (
        <div className="max-h-72 overflow-auto rounded-lg border border-gray-200">
          <table className="min-w-full text-sm">
            <thead className="sticky top-0 bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
              <tr><th className="px-3 py-2">Day</th>{rows[0]?.transactions !== undefined && <th className="px-3 py-2 text-right">Sales</th>}<th className="px-3 py-2 text-right">Revenue</th><th className="px-3 py-2 text-right">Gross profit</th></tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((r) => (
                <tr key={r.day}><td className="px-3 py-1.5">{dayLabel(r.day)}</td>{r.transactions !== undefined && <td className="px-3 py-1.5 text-right tabular-nums">{r.transactions}</td>}
                  <td className="px-3 py-1.5 text-right tabular-nums">{formatKES(r.revenue)}</td><td className="px-3 py-1.5 text-right tabular-nums">{formatKES(r.gross_profit)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="h-72" role="img" aria-label={`Daily revenue and gross profit${last ? `; latest day revenue ${formatKES(last.revenue)}` : ''}`}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#eef0f2" vertical={false} />
              <XAxis dataKey="day" tickFormatter={dayLabel} tick={{ fontSize: 11, fill: '#6b7280' }} tickLine={false} axisLine={{ stroke: '#e5e7eb' }} minTickGap={24} />
              <YAxis tickFormatter={compact} tick={{ fontSize: 11, fill: '#6b7280' }} tickLine={false} axisLine={false} width={48} />
              <Tooltip content={<ChartTooltip />} cursor={{ stroke: '#9ca3af', strokeWidth: 1 }} />
              <Line type="monotone" dataKey="revenue" name="Revenue" stroke={SERIES.revenue} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: '#fff' }} isAnimationActive={false} />
              <Line type="monotone" dataKey="gross_profit" name="Gross profit" stroke={SERIES.profit} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: '#fff' }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

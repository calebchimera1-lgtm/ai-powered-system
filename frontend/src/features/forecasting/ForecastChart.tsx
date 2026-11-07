import { useState } from 'react';
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import type { SeriesPoint } from '@/api/analytics';

// One entity (this product's demand), one hue: categorical slot 1 of the validated chart
// palette (the same blue as revenue on the finance page). Actual and forecast are told
// apart by line style (solid vs dashed), by the shaded range, by the "Today" marker and by
// the legend, never by colour alone.
const HUE = '#2a78d6';

const dayLabel = (iso: string) =>
  new Intl.DateTimeFormat('en-KE', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(`${iso}T00:00:00Z`));
const weekday = (iso: string) =>
  new Intl.DateTimeFormat('en-KE', { weekday: 'short', timeZone: 'UTC' }).format(new Date(`${iso}T00:00:00Z`));
const fmt = (n: number | null | undefined) => (n === null || n === undefined ? '—' : n.toLocaleString('en-KE', { maximumFractionDigits: 1 }));

type Row = SeriesPoint & { band: [number, number] | null };

function ChartTooltip({ active, payload, unit }: { active?: boolean; payload?: { payload: Row }[]; unit: string }) {
  if (!active || !payload?.length) return null;
  const p = payload[0]!.payload;
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 font-semibold text-gray-900">{weekday(p.date)} {dayLabel(p.date)}</p>
      {p.actual !== null && p.actual !== undefined && (
        <p className="flex items-center gap-2 text-gray-700"><span className="h-0.5 w-3" style={{ background: HUE }} />Sold <span className="ml-auto pl-3 tabular-nums text-gray-900">{fmt(p.actual)} {unit}</span></p>
      )}
      {p.forecast !== null && p.forecast !== undefined && (
        <>
          <p className="flex items-center gap-2 text-gray-700"><span className="w-3 border-t-2 border-dashed" style={{ borderColor: HUE }} />Forecast <span className="ml-auto pl-3 tabular-nums text-gray-900">{fmt(p.forecast)} {unit}</span></p>
          <p className="text-gray-500">80% range {fmt(p.lower)} to {fmt(p.upper)}</p>
        </>
      )}
    </div>
  );
}

/** Actual daily sales (solid) and the forecast (dashed) with its 80% range (shaded). */
export function ForecastChart({ series, today, unit }: { series: SeriesPoint[]; today: string; unit: string }) {
  const [asTable, setAsTable] = useState(false);
  const rows: Row[] = series.map((p) => ({
    ...p,
    band: p.lower !== null && p.lower !== undefined && p.upper !== null && p.upper !== undefined ? [p.lower, p.upper] : null,
  }));
  const future = rows.filter((r) => r.forecast !== null && r.forecast !== undefined);
  const nextWeek = future.slice(0, 7).reduce((a, r) => a + (r.forecast ?? 0), 0);
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <ul className="flex flex-wrap gap-4 text-xs text-gray-600" aria-label="Legend">
          <li className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded" style={{ background: HUE }} />Actual sales</li>
          <li className="flex items-center gap-1.5"><span className="w-4 border-t-2 border-dashed" style={{ borderColor: HUE }} />Forecast</li>
          <li className="flex items-center gap-1.5"><span className="h-3 w-4 rounded-sm" style={{ background: HUE, opacity: 0.18 }} />80% range</li>
        </ul>
        <button type="button" onClick={() => setAsTable((v) => !v)} className="text-xs font-medium text-brand-700 hover:underline">
          {asTable ? 'Show chart' : 'Show as table'}
        </button>
      </div>
      {asTable ? (
        <div className="max-h-80 overflow-auto rounded-lg border border-gray-200">
          <table className="min-w-full text-sm">
            <thead className="sticky top-0 bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
              <tr><th className="px-3 py-2">Day</th><th className="px-3 py-2 text-right">Sold</th><th className="px-3 py-2 text-right">Forecast</th><th className="px-3 py-2 text-right">80% range</th></tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((r) => (
                <tr key={r.date} className={r.date === today ? 'bg-brand-50/50' : undefined}>
                  <td className="whitespace-nowrap px-3 py-1.5">{weekday(r.date)} {dayLabel(r.date)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{fmt(r.actual)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{fmt(r.forecast)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{r.band ? `${fmt(r.band[0])}–${fmt(r.band[1])}` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="h-72" role="img" aria-label={`Daily sales for the last ${rows.length - future.length} days and a forecast of about ${fmt(nextWeek)} ${unit} over the next 7 days`}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 16, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#eef0f2" vertical={false} />
              <XAxis dataKey="date" tickFormatter={dayLabel} tick={{ fontSize: 11, fill: '#6b7280' }} tickLine={false} axisLine={{ stroke: '#e5e7eb' }} minTickGap={28} />
              <YAxis tick={{ fontSize: 11, fill: '#6b7280' }} tickLine={false} axisLine={false} width={40} allowDecimals={false} />
              <Tooltip content={<ChartTooltip unit={unit} />} cursor={{ stroke: '#9ca3af', strokeWidth: 1 }} />
              <Area dataKey="band" stroke="none" fill={HUE} fillOpacity={0.16} isAnimationActive={false} activeDot={false} connectNulls={false} />
              <Line dataKey="actual" stroke={HUE} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: '#fff' }} isAnimationActive={false} connectNulls={false} />
              <Line dataKey="forecast" stroke={HUE} strokeWidth={2} strokeDasharray="5 4" dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: '#fff' }} isAnimationActive={false} connectNulls={false} />
              <ReferenceLine x={today} stroke="#6b7280" strokeDasharray="2 3" label={{ value: 'Today', position: 'top', fill: '#4b5563', fontSize: 11 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

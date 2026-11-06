import clsx from 'clsx';
import type { LucideIcon } from 'lucide-react';
import { Link } from 'react-router-dom';

const tones = {
  green: 'bg-brand-50 text-brand-700',
  red: 'bg-red-50 text-red-700',
  amber: 'bg-amber-50 text-amber-700',
  blue: 'bg-blue-50 text-blue-700',
  gray: 'bg-gray-100 text-gray-600',
};

export function StatCard({
  label,
  value,
  icon: Icon,
  tone = 'gray',
  to,
  hint,
}: {
  label: string;
  value: string | number;
  icon: LucideIcon;
  tone?: keyof typeof tones;
  to?: string;
  hint?: string;
}) {
  const body = (
    <div className="flex items-start gap-3">
      <span className={clsx('rounded-lg p-2', tones[tone])}>
        <Icon className="h-5 w-5" aria-hidden />
      </span>
      <div className="min-w-0">
        <p className="text-sm text-gray-500">{label}</p>
        <p className="mt-0.5 break-words text-lg font-semibold leading-tight tabular-nums text-gray-900 sm:text-xl">{value}</p>
        {hint && <p className="text-xs text-gray-400">{hint}</p>}
      </div>
    </div>
  );
  const cls = 'block rounded-xl border border-gray-200 bg-white p-4 shadow-card';
  return to ? (
    <Link to={to} className={clsx(cls, 'transition-colors hover:border-brand-300')}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}

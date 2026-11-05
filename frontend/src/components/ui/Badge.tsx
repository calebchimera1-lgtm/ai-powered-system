import clsx from 'clsx';
import type { ReactNode } from 'react';

type Tone = 'green' | 'gray' | 'red' | 'amber' | 'blue';

const tones: Record<Tone, string> = {
  green: 'bg-brand-50 text-brand-700 ring-brand-600/20',
  gray: 'bg-gray-100 text-gray-700 ring-gray-500/20',
  red: 'bg-red-50 text-red-700 ring-red-600/20',
  amber: 'bg-amber-50 text-amber-800 ring-amber-600/20',
  blue: 'bg-blue-50 text-blue-700 ring-blue-600/20',
};

export function Badge({ tone = 'gray', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset',
        tones[tone],
      )}
    >
      {children}
    </span>
  );
}

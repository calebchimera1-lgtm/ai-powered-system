import clsx from 'clsx';
import { Loader2 } from 'lucide-react';

export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-gray-500">
      <Loader2 className={clsx('h-5 w-5 animate-spin', className)} aria-hidden />
      <span className={label ? 'text-sm' : 'sr-only'}>{label ?? 'Loading'}</span>
    </span>
  );
}

export function FullPageSpinner({ label }: { label?: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <Spinner className="h-8 w-8 text-brand-600" label={label} />
    </div>
  );
}

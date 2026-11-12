import { Boxes } from 'lucide-react';
import type { ReactNode } from 'react';

import { AppFooter } from '@/components/layout/AppFooter';
import { usePageTitle } from '@/hooks/usePageTitle';

export function AuthLayout({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  usePageTitle(title);
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gradient-to-b from-brand-50 to-gray-50 px-4 py-10">
      <div className="mb-6 flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm">
          <Boxes className="h-6 w-6" aria-hidden />
        </div>
        <div>
          <p className="text-lg font-semibold text-gray-900">Smart Inventory</p>
          <p className="text-sm text-gray-500">Supermarket management suite</p>
        </div>
      </div>
      <div className="w-full max-w-sm rounded-2xl border border-gray-200 bg-white p-6 shadow-card sm:p-8">
        <h1 className="text-xl font-semibold text-gray-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-gray-500">{subtitle}</p>}
        <div className="mt-6">{children}</div>
      </div>
      <AppFooter signedIn={false} className="mt-8" />
    </div>
  );
}

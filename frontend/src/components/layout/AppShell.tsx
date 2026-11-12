import { Suspense, useCallback, useState } from 'react';
import { Outlet } from 'react-router-dom';

import { Spinner } from '@/components/ui/Spinner';

import { AppFooter } from './AppFooter';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';

export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);
  const close = useCallback(() => setMenuOpen(false), []);
  return (
    <div className="flex min-h-screen bg-gray-50">
      <a href="#main" className="sr-only z-50 rounded-lg bg-white px-4 py-2 font-medium text-brand-700 shadow focus:not-sr-only focus:fixed focus:left-3 focus:top-3">
        Skip to content
      </a>
      <Sidebar mobileOpen={menuOpen} onClose={close} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpenMenu={() => setMenuOpen(true)} menuOpen={menuOpen} />
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 focus:outline-none sm:px-6 lg:px-8">
          <Suspense fallback={<div className="flex justify-center py-20"><Spinner label="Loading page…" /></div>}>
            <Outlet />
          </Suspense>
        </main>
        <AppFooter className="mx-auto w-full max-w-7xl border-t border-gray-200 px-4 py-4 sm:px-6 lg:px-8" />
      </div>
    </div>
  );
}

import clsx from 'clsx';
import { Boxes, X } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';

import { useAuth } from '@/auth/AuthProvider';

import { visibleSections } from './navigation';

/** The logo; it links to the home page. */
function Brand({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <Link to="/" onClick={onNavigate} aria-label="Smart Inventory, home" className="-m-1 flex items-center gap-2.5 rounded-lg p-1">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 text-white">
        <Boxes className="h-5 w-5" aria-hidden />
      </div>
      <div className="leading-tight">
        <p className="text-sm font-semibold text-gray-900">Smart Inventory</p>
        <p className="text-xs text-gray-500">Supermarket suite</p>
      </div>
    </Link>
  );
}

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const { canAny } = useAuth();
  return (
    <nav aria-label="Main navigation" className="flex-1 space-y-6 overflow-y-auto px-3 py-4">
      {visibleSections(canAny).map((section) => (
        <div key={section.title}>
          <p className="px-3 pb-2 text-xs font-semibold uppercase tracking-wider text-gray-400">
            {section.title}
          </p>
          <ul className="space-y-0.5">
            {section.items.map(({ to, label, icon: Icon }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={to === '/'}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    clsx(
                      'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                      isActive
                        ? 'bg-brand-50 text-brand-700'
                        : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900',
                    )
                  }
                >
                  <Icon className="h-5 w-5 shrink-0" aria-hidden />
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

export function Sidebar({ mobileOpen, onClose }: { mobileOpen: boolean; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const location = useLocation();

  // Close the drawer when the page changes (back button, a link inside a page, etc.).
  useEffect(() => {
    onClose();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  // While open: Escape closes it, focus moves into it and stays there, the page behind
  // does not scroll, and focus returns to the menu button when it closes.
  useEffect(() => {
    if (!mobileOpen) return;
    const opener = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      if (e.key !== 'Tab') return;
      const drawer = closeRef.current?.closest('aside');
      const focusable = drawer?.querySelectorAll<HTMLElement>('a[href], button:not([disabled])');
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previousOverflow;
      opener?.focus?.();
    };
  }, [mobileOpen, onClose]);

  return (
    <>
      {/* Desktop */}
      <aside className="hidden w-64 shrink-0 flex-col border-r border-gray-200 bg-white lg:flex">
        <div className="flex h-16 items-center border-b border-gray-100 px-5">
          <Brand />
        </div>
        <NavList />
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div id="mobile-menu" className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <div className="absolute inset-0 bg-gray-900/50" onClick={onClose} aria-hidden />
          <aside className="relative flex h-full w-72 max-w-[85vw] flex-col bg-white shadow-xl">
            <div className="flex h-16 items-center justify-between border-b border-gray-100 px-4">
              <Brand onNavigate={onClose} />
              <button
                ref={closeRef}
                type="button"
                onClick={onClose}
                className="rounded-lg p-2.5 text-gray-500 hover:bg-gray-100"
                aria-label="Close menu"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <NavList onNavigate={onClose} />
          </aside>
        </div>
      )}
    </>
  );
}

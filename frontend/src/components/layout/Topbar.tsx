import { ChevronDown, LogOut, Menu, UserCircle } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { useAuth } from '@/auth/AuthProvider';

import { NotificationBell } from './NotificationBell';

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join('');
}

export function Topbar({ onOpenMenu, menuOpen = false }: { onOpenMenu: () => void; menuOpen?: boolean }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  if (!user) return null;

  const handleLogout = async () => {
    setOpen(false);
    await logout();
    navigate('/login', { replace: true });
  };

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-4 border-b border-gray-200 bg-white/95 px-4 backdrop-blur sm:px-6">
      <button
        type="button"
        onClick={onOpenMenu}
        className="rounded-lg p-2.5 text-gray-600 hover:bg-gray-100 lg:hidden"
        aria-label="Open menu"
        aria-expanded={menuOpen}
        aria-controls="mobile-menu"
      >
        <Menu className="h-5 w-5" />
      </button>
      <div className="flex-1" />
      <NotificationBell />
      <div className="relative" ref={menuRef}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 rounded-lg p-1.5 hover:bg-gray-100"
          aria-haspopup="menu"
          aria-expanded={open}
        >
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-100 text-sm font-semibold text-brand-700">
            {initials(user.full_name)}
          </span>
          <span className="hidden text-left sm:block">
            <span className="block text-sm font-medium text-gray-900">{user.full_name}</span>
            <span className="block text-xs text-gray-500">{user.role.display_name}</span>
          </span>
          <ChevronDown className="h-4 w-4 text-gray-400" aria-hidden />
        </button>
        {open && (
          <div
            role="menu"
            className="absolute right-0 mt-2 w-56 overflow-hidden rounded-xl border border-gray-200 bg-white py-1 shadow-lg"
          >
            <div className="border-b border-gray-100 px-4 py-2.5 sm:hidden">
              <p className="text-sm font-medium text-gray-900">{user.full_name}</p>
              <p className="text-xs text-gray-500">{user.role.display_name}</p>
            </div>
            <Link
              to="/account"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
            >
              <UserCircle className="h-4 w-4" aria-hidden /> My account
            </Link>
            <button
              type="button"
              role="menuitem"
              onClick={handleLogout}
              className="flex w-full items-center gap-2 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
            >
              <LogOut className="h-4 w-4" aria-hidden /> Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}

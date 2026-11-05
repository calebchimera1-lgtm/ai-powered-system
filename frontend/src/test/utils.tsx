import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';

import type { CurrentUser, RoleName } from '@/api/types';
import { AuthProvider } from '@/auth/AuthProvider';
import { ToastProvider } from '@/components/ui/Toast';

const ROLE_PERMS: Record<RoleName, string[]> = {
  super_admin: ['users:read', 'users:manage', 'roles:read', 'audit:read'],
  store_manager: ['users:read', 'roles:read'],
  inventory_officer: ['products:read'],
  cashier: ['products:read', 'sales:create'],
};

export function makeUser(role: RoleName, overrides: Partial<CurrentUser> = {}): CurrentUser {
  return {
    id: 1,
    full_name: 'Amina Wanjiru',
    username: 'amina',
    email: 'amina@test.local',
    phone: null,
    role: { id: 1, name: role, display_name: role.replace('_', ' ') },
    permissions: ROLE_PERMS[role],
    must_change_password: false,
    last_login_at: null,
    ...overrides,
  };
}

export function renderWithProviders(ui: ReactElement, { route = '/' }: { route?: string } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={[route]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <AuthProvider>{ui}</AuthProvider>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

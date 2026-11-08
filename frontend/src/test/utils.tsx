import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';

import type { CurrentUser, RoleName } from '@/api/types';
import { AuthProvider } from '@/auth/AuthProvider';
import { ToastProvider } from '@/components/ui/Toast';

const ROLE_PERMS: Record<RoleName, string[]> = {
  super_admin: [
    'users:read', 'users:manage', 'roles:read', 'audit:read', 'products:read', 'products:write',
    'products:delete', 'products:view_cost', 'stock:read', 'stock:adjust', 'stock:adjust_approve',
    'stock:adjust_negative', 'stock:write_off', 'suppliers:read', 'suppliers:write',
    'backups:manage',
  ],
  store_manager: [
    'users:read', 'roles:read', 'products:read', 'products:write', 'products:delete',
    'products:view_cost', 'stock:read', 'stock:adjust', 'stock:adjust_approve', 'stock:write_off',
    'suppliers:read', 'suppliers:write', 'purchases:read', 'purchases:write', 'forecasts:read',
    'anomalies:read', 'anomalies:review',
  ],
  inventory_officer: [
    'products:read', 'products:write', 'products:view_cost', 'stock:read', 'stock:adjust',
    'stock:write_off', 'suppliers:read', 'suppliers:write', 'purchases:read', 'purchases:write',
    'invoices:upload', 'invoices:approve', 'forecasts:read',
  ],
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

export function makeProduct(overrides: Partial<import('@/api/types').Product> = {}): import('@/api/types').Product {
  return {
    id: 7,
    sku: 'SUG-2KG',
    barcode: '2000000000015',
    name: 'White Sugar 2kg',
    description: null,
    category: { id: 1, name: 'Dry goods' },
    default_supplier: null,
    unit_of_measure: 'pcs',
    image_url: null,
    selling_price: '245.00',
    vat_rate: '16.00',
    quantity_on_hand: '46.000',
    min_stock_level: '15.000',
    max_stock_level: '150.000',
    reorder_lead_time_days: 3,
    tracks_expiry: false,
    is_active: true,
    stock_status: 'ok',
    next_expiry: null,
    created_at: '2026-11-01T08:00:00Z',
    updated_at: '2026-11-01T08:00:00Z',
    ...overrides,
  };
}

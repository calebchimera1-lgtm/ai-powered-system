import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { dashboardApi, reportsApi, type Dashboard } from '@/api/analytics';
import { categoriesApi } from '@/api/catalog';
import * as client from '@/api/client';
import { ReportsPage } from '@/features/reports/ReportsPage';
import { makeUser, renderWithProviders } from '@/test/utils';

import { DashboardPage, rangeFor } from './DashboardPage';

vi.mock('@/api/analytics', () => ({
  dashboardApi: { get: vi.fn() },
  reportsApi: { list: vi.fn(), download: vi.fn() },
  notificationsApi: { unreadCount: vi.fn() },
}));
vi.mock('@/api/catalog', () => ({ categoriesApi: { list: vi.fn() } }));

function data(overrides: Partial<Dashboard> = {}): Dashboard {
  return {
    date_from: '2026-10-10', date_to: '2026-11-08', category_id: null,
    inventory: { total_products: 10, out_of_stock: 1, low_stock: 2, expiring_soon: 1, inventory_value: '84652.77',
      low_stock_items: [{ product_id: 5, name: 'Fresh Milk 500ml', on_hand: '4', min_stock: '20', unit: 'pcs' }],
      expiring_items: [{ product_id: 5, name: 'Fresh Milk 500ml', expiry_date: '2026-11-10', quantity: '24', unit: 'pcs', expired: false }] },
    movers: { fast: [{ product_id: 5, name: 'Fresh Milk 500ml', unit: 'pcs', per_day: 57.5, on_hand: '108', days_of_cover: 1.9 }],
      slow: [{ product_id: 7, name: 'Bar Soap 800g', unit: 'pcs', per_day: 6.2, on_hand: '38', days_of_cover: 6.1 }] },
    shortages: [{ product_id: 8, name: 'Bottled Water 1L', stockout_date: '2026-11-09', lead_time_days: 5, suggested_quantity: '206', unit: 'pcs' }],
    approvals: { invoices_to_review: 1, purchase_orders_draft: 0, purchase_orders_open: 2, adjustments_pending: 1, returns_pending: 0 },
    sales: { today_revenue: '12500.00', today_transactions: 31, month_revenue: '139550.06', month_gross_profit: '19998.81',
      period_revenue: '929446.70', period_gross_profit: '138868.87', period_transactions: 1920, gross_margin_percent: '14.94',
      trend: [{ day: '2026-11-07', revenue: '30000', gross_profit: '4500' }, { day: '2026-11-08', revenue: '12500', gross_profit: '1900' }] },
    categories: [{ category: 'Dry goods', revenue: '573459.85', gross_profit: '56701.49' }],
    open_irregularities: 3,
    ...overrides,
  };
}

function login(role: 'store_manager' | 'inventory_officer' | 'cashier' = 'store_manager') {
  vi.spyOn(client, 'refreshAccessToken').mockResolvedValue({ access_token: 't', token_type: 'bearer', expires_in: 900, user: makeUser(role) });
}

describe('rangeFor', () => {
  const now = new Date(2026, 10, 8);
  it('ends today and counts the days inclusively', () => {
    expect(rangeFor('7', now)).toEqual({ from: '2026-11-02', to: '2026-11-08' });
    expect(rangeFor('30', now)).toEqual({ from: '2026-10-10', to: '2026-11-08' });
    expect(rangeFor('month', now)).toEqual({ from: '2026-11-01', to: '2026-11-08' });
  });
});

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(categoriesApi.list).mockResolvedValue([{ id: 2, name: 'Dairy' }] as never);
  });

  it('shows the figures, the attention panel and filters by category', async () => {
    login();
    vi.mocked(dashboardApi.get).mockResolvedValue(data());
    renderWithProviders(<DashboardPage greeting="Good morning" />);
    expect(await screen.findByText('KES 929,446.70')).toBeInTheDocument();
    expect(screen.getByText('14.9% margin')).toBeInTheDocument();
    expect(screen.getByText('Irregularities to review')).toBeInTheDocument();
    expect(screen.getByText('1 invoices · 1 adjustments')).toBeInTheDocument();
    expect(screen.getByText('Revenue by category')).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('Category'), '2');
    await waitFor(() => expect(dashboardApi.get).toHaveBeenLastCalledWith(expect.objectContaining({ category_id: 2 })));
    await userEvent.click(screen.getByRole('radio', { name: '7 days' }));
    await waitFor(() => {
      const last = vi.mocked(dashboardApi.get).mock.calls.at(-1)![0];
      expect(last.date_from).toBe(rangeFor('7').from);
    });
  });

  it('hides money figures when the server withholds them', async () => {
    login('inventory_officer');
    vi.mocked(dashboardApi.get).mockResolvedValue(data({ sales: null, categories: null, open_irregularities: null,
      inventory: { ...data().inventory, inventory_value: null } }));
    renderWithProviders(<DashboardPage greeting="Hello" />);
    expect(await screen.findByText('Predicted shortages', { selector: 'span' })).toBeInTheDocument();
    expect(screen.queryByText("Today's sales")).not.toBeInTheDocument();
    expect(screen.queryByText('Irregularities to review')).not.toBeInTheDocument();
    expect(screen.getByText('Fast movers')).toBeInTheDocument();
  });
});

describe('ReportsPage', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('downloads the chosen report with the period and category', async () => {
    login();
    vi.mocked(categoriesApi.list).mockResolvedValue([{ id: 2, name: 'Dairy' }] as never);
    vi.mocked(reportsApi.list).mockResolvedValue([
      { key: 'daily-sales', title: 'Daily sales', description: 'Sales per day', uses_period: true, formats: ['pdf', 'xlsx', 'csv'] },
      { key: 'inventory-valuation', title: 'Inventory valuation', description: 'Stock value', uses_period: false, formats: ['pdf', 'xlsx', 'csv'] },
    ]);
    vi.mocked(reportsApi.download).mockResolvedValue('daily-sales.xlsx');
    renderWithProviders(<ReportsPage />);
    await userEvent.selectOptions(await screen.findByLabelText('Category'), '2');
    await userEvent.click(screen.getByRole('button', { name: 'Download Daily sales as Excel' }));
    const range = rangeFor('30');
    expect(reportsApi.download).toHaveBeenCalledWith('daily-sales', { format: 'xlsx', category_id: 2, date_from: range.from, date_to: range.to });
    await userEvent.click(screen.getByRole('button', { name: 'Download Inventory valuation as PDF' }));
    expect(reportsApi.download).toHaveBeenLastCalledWith('inventory-valuation', { format: 'pdf', category_id: 2 });
    expect((await screen.findAllByText('Report downloaded')).length).toBe(2);
  });
});

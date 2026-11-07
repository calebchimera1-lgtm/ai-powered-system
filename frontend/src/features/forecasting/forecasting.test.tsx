import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { forecastsApi, notificationsApi, type ProductForecast } from '@/api/analytics';
import * as client from '@/api/client';
import { NotificationBell } from '@/components/layout/NotificationBell';
import { makeUser, renderWithProviders } from '@/test/utils';

import { ForecastChart } from './ForecastChart';
import { ForecastsPage } from './ForecastsPage';
import { daysUntil, stockoutTone } from './labels';

vi.mock('@/api/analytics', () => ({
  forecastsApi: { overview: vi.fn(), run: vi.fn() },
  notificationsApi: { unreadCount: vi.fn(), list: vi.fn(), markRead: vi.fn() },
}));

const NOW = new Date(2026, 10, 7); // 7 Nov 2026

function pf(overrides: Partial<ProductForecast> = {}): ProductForecast {
  return {
    product: { id: 1, name: 'White Sugar 2kg', sku: 'SKU-1', unit_of_measure: 'pcs' }, model_name: 'holt_winters',
    model_label: 'Holt-Winters (weekly seasonality)', low_confidence: false, history_days: 365, avg_daily_28: 14.5,
    demand_pattern: 'smooth', adi: 1, cv2: 0.2, abc_class: 'A', revenue_90d: '300000', weekday_profile: [1, 1, 1, 1, 1, 1.3, 1.2],
    payday_effect: 1.35, on_hand: '30', on_order: '0', lead_time_days: 5, stockout_date: '2026-11-09', days_of_cover: 2.1,
    safety_stock: 12, reorder_point: 85, should_order: true, suggested_quantity: '170', residual_std: 4, next_7_days: 98,
    next_28_days: 410, chosen_mase: 0.7, seasonal_naive_mase: 1, ...overrides,
  };
}

function login(role: 'inventory_officer' | 'cashier' = 'inventory_officer') {
  vi.spyOn(client, 'refreshAccessToken').mockResolvedValue({ access_token: 't', token_type: 'bearer', expires_in: 900, user: makeUser(role) });
}

describe('forecast helpers', () => {
  it('counts days and colours stock-outs against the lead time', () => {
    expect(daysUntil('2026-11-09', NOW)).toBe(2);
    expect(stockoutTone({ stockout_date: '2026-11-09', lead_time_days: 5 }, NOW)).toBe('red');
    expect(stockoutTone({ stockout_date: '2026-11-15', lead_time_days: 5 }, NOW)).toBe('amber');
    expect(stockoutTone({ stockout_date: '2026-12-01', lead_time_days: 5 }, NOW)).toBe('gray');
    expect(stockoutTone({ stockout_date: null, lead_time_days: 5 }, NOW)).toBe('gray');
  });
});

describe('ForecastsPage', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('lists products by urgency with the suggested order and the baseline comparison', async () => {
    login();
    vi.mocked(notificationsApi.unreadCount).mockResolvedValue(0);
    vi.mocked(forecastsApi.overview).mockResolvedValue({
      running: false,
      run: { id: 3, started_at: '2026-11-07T01:00:00Z', finished_at: '2026-11-07T01:00:20Z', status: 'SUCCEEDED',
        history_start: '2025-11-07', history_end: '2026-11-06', horizon_days: 28, params: null, error_message: null,
        summary: { beats_seasonal_naive: 9, compared_with_seasonal_naive: 10 } },
      products: [pf(), pf({ product: { id: 2, name: 'Pishori Rice 2kg', sku: 'SKU-2', unit_of_measure: 'pcs' }, should_order: false, stockout_date: null, days_of_cover: null })],
    });
    renderWithProviders(<Routes><Route path="/forecasts" element={<ForecastsPage />} /></Routes>, { route: '/forecasts' });
    expect(await screen.findByText('White Sugar 2kg')).toBeInTheDocument();
    expect(screen.getByText('9 of 10')).toBeInTheDocument();
    expect(screen.getByText('170 pcs')).toBeInTheDocument();
    expect(screen.getByText('Not within 4 weeks')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reorder suggestions \(1\)/i })).toBeInTheDocument();
  });
});

describe('ForecastChart', () => {
  it('offers the same numbers as a table', async () => {
    renderWithProviders(
      <ForecastChart unit="pcs" today="2026-11-07" series={[
        { date: '2026-11-06', actual: 12, forecast: null, lower: null, upper: null },
        { date: '2026-11-07', actual: null, forecast: 14.2, lower: 9.5, upper: 19 },
      ]} />,
    );
    expect(screen.getByText('Actual sales')).toBeInTheDocument();
    expect(screen.getByText('80% range')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /show as table/i }));
    expect(screen.getByText('14.2')).toBeInTheDocument();
    expect(screen.getByText('9.5–19')).toBeInTheDocument();
  });
});

describe('NotificationBell', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('shows the unread count and marks a notification read when opened', async () => {
    login();
    vi.mocked(notificationsApi.unreadCount).mockResolvedValue(2);
    vi.mocked(notificationsApi.markRead).mockResolvedValue({ updated: 1 });
    vi.mocked(notificationsApi.list).mockResolvedValue({ total: 2, unread: 2, items: [
      { id: 7, type: 'LOW_STOCK', title: 'Low stock: White Sugar 2kg', message: 'Down to 8 pcs', link: '/products/1', severity: 'warning', is_read: false, created_at: '2026-11-07T08:00:00Z' },
      { id: 6, type: 'EXPIRY', title: 'Fresh Milk: batch expires in 2 days', message: '…', link: null, severity: 'critical', is_read: false, created_at: '2026-11-07T07:00:00Z' },
    ] });
    renderWithProviders(<Routes><Route path="/" element={<NotificationBell />} /><Route path="/products/1" element={<p>Product page</p>} /></Routes>);
    const bell = await screen.findByRole('button', { name: 'Notifications, 2 unread' });
    await userEvent.click(bell);
    await userEvent.click(await screen.findByText('Low stock: White Sugar 2kg'));
    expect(notificationsApi.markRead).toHaveBeenCalledWith([7]);
    expect(await screen.findByText('Product page')).toBeInTheDocument();
  });
});

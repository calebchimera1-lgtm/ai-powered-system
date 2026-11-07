import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { anomaliesApi, type AnomalyAlert } from '@/api/analytics';
import * as client from '@/api/client';
import { makeUser, renderWithProviders } from '@/test/utils';

import { AnomalyDetailPage } from './AnomalyDetailPage';

vi.mock('@/api/analytics', () => ({
  anomaliesApi: { get: vi.fn(), review: vi.fn() },
  notificationsApi: { unreadCount: vi.fn(), list: vi.fn() },
}));

function alert(overrides: Partial<AnomalyAlert> = {}): AnomalyAlert {
  return {
    id: 4, entity_type: 'product', product: { id: 2, name: 'Pishori Rice 2kg', sku: 'SKU-2', unit_of_measure: 'pcs' },
    subject_user: null, kind: 'UNEXPLAINED_STOCK_LOSS', kind_label: 'Unexplained stock loss', detected_at: '2026-11-07T06:00:00Z',
    period_start: '2026-11-03', period_end: '2026-11-05', quantity: 27, value_kes: '8100.00', severity: 'HIGH', score: 0.9,
    detector: 'BOTH', explanation: '9 units of Pishori Rice 2kg were adjusted out of stock on 03 Nov, against a typical 0 a day.',
    recommended_action: 'Count the product on the shelf and in the store room.',
    evidence: [{ day: '2026-11-03', detector: 'BOTH', score: 0.9, explanation: '', figures: { adj_out: { value: 9, normal: 0, z: 9 } } }],
    status: 'OPEN', reviewed_by: null, reviewed_at: null, review_notes: null, ...overrides,
  };
}

function renderPage(role: 'store_manager' | 'inventory_officer' = 'store_manager', userId = 1) {
  vi.spyOn(client, 'refreshAccessToken').mockResolvedValue({ access_token: 't', token_type: 'bearer', expires_in: 900, user: makeUser(role, { id: userId }) });
  return renderWithProviders(<Routes><Route path="/anomalies/:id" element={<AnomalyDetailPage />} /></Routes>, { route: '/anomalies/4' });
}

describe('AnomalyDetailPage', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('shows the explanation and evidence, and needs a note to resolve', async () => {
    vi.mocked(anomaliesApi.get).mockResolvedValue(alert());
    vi.mocked(anomaliesApi.review).mockResolvedValue(alert({ status: 'RESOLVED_ISSUE_FOUND', review_notes: 'Recount: 9 bags missing' }));
    renderPage();
    expect(await screen.findByText(/9 units of Pishori Rice 2kg/)).toBeInTheDocument();
    expect(screen.getByText('3 Nov – 5 Nov', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('Units adjusted out')).toBeInTheDocument();
    expect(screen.getByText('normal 0')).toBeInTheDocument();
    expect(screen.getByText(/rule and pattern model/i)).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText(/issue found/i));
    const save = screen.getByRole('button', { name: /save review/i });
    expect(save).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/notes/i), 'Recount: 9 bags missing');
    await userEvent.click(save);
    await waitFor(() => expect(anomaliesApi.review).toHaveBeenCalledWith(4, 'RESOLVED_ISSUE_FOUND', 'Recount: 9 bags missing'));
  });

  it('does not let people review alerts about themselves', async () => {
    vi.mocked(anomaliesApi.get).mockResolvedValue(alert({
      entity_type: 'user', product: null, subject_user: { id: 1, username: 'amina', full_name: 'Amina Wanjiru' },
      kind: 'FREQUENT_ADJUSTMENTS', kind_label: 'Unusually many adjustments',
    }));
    renderPage('store_manager', 1);
    expect(await screen.findByText(/about your own activity/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /save review/i })).not.toBeInTheDocument();
  });
});

import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '@/api/client';
import { salesApi } from '@/api/sales';
import type { Sale } from '@/api/types';
import { makeUser, renderWithProviders } from '@/test/utils';

import { ReturnModal } from './ReturnModal';

vi.mock('@/api/sales', () => ({ salesApi: { createReturn: vi.fn() } }));

const sale = {
  id: 9, receipt_number: 'RCPT-2026-000009', sold_at: '2026-11-06T10:00:00Z', status: 'COMPLETED',
  cashier: { id: 1, username: 'a', full_name: 'A' }, customer: null, subtotal: '805.00', discount_total: '20.00',
  tax_total: '108.28', grand_total: '785.00', cost_total: null, gross_profit: null, payment_method: 'MPESA',
  payment_reference: 'SKD4H2L9QX', amount_tendered: null, change_given: null, notes: null,
  items: [
    { id: 1, product_id: 7, product_name: 'White Sugar 2kg', quantity: '3.000', unit_price: '245.00', discount_amount: '18.26', vat_rate: '16', tax_amount: '98.86', line_total: '716.74', returned_quantity: '1.000', unit_cost: null },
    { id: 2, product_id: 8, product_name: 'White Bread 400g', quantity: '1.000', unit_price: '70.00', discount_amount: '1.74', vat_rate: '16', tax_amount: '9.42', line_total: '68.26', returned_quantity: '1.000', unit_cost: null },
  ],
} satisfies Sale;

describe('ReturnModal', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(client, 'refreshAccessToken').mockResolvedValue({ access_token: 't', token_type: 'bearer', expires_in: 900, user: makeUser('cashier') });
  });

  it('lists only what can still be returned and sends the chosen lines', async () => {
    vi.mocked(salesApi.createReturn).mockResolvedValue({} as never);
    renderWithProviders(<ReturnModal sale={sale} onClose={() => {}} onDone={() => {}} />);
    expect(await screen.findByText(/can return 2/)).toBeInTheDocument();
    expect(screen.queryByText('White Bread 400g')).not.toBeInTheDocument(); // fully returned already
    await userEvent.type(screen.getByLabelText('Quantity of White Sugar 2kg to return'), '1');
    await userEvent.selectOptions(screen.getByLabelText('Condition of White Sugar 2kg'), 'DAMAGED');
    await userEvent.type(screen.getByLabelText(/reason/i), 'Torn bag');
    const submit = screen.getByRole('button', { name: /record return/i });
    expect(submit).toHaveTextContent('KES 238.91'); // 716.74 / 3
    await userEvent.click(submit);
    expect(salesApi.createReturn).toHaveBeenCalledWith(9, {
      items: [{ sale_item_id: 1, quantity: '1', condition: 'DAMAGED' }], reason: 'Torn bag', refund_method: 'MPESA',
    });
  });

  it('rejects more than can be returned', async () => {
    renderWithProviders(<ReturnModal sale={sale} onClose={() => {}} onDone={() => {}} />);
    await userEvent.type(await screen.findByLabelText('Quantity of White Sugar 2kg to return'), '3');
    await userEvent.type(screen.getByLabelText(/reason/i), 'Too many');
    expect(screen.getByText(/more than can be returned/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /record return/i })).toBeDisabled();
  });
});

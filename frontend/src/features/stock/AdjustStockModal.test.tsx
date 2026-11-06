import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '@/api/client';
import { stockApi } from '@/api/stock';
import type { RoleName } from '@/api/types';
import { makeProduct, makeUser, renderWithProviders } from '@/test/utils';

import { AdjustStockModal } from './AdjustStockModal';

vi.mock('@/api/stock', () => ({ stockApi: { adjust: vi.fn() } }));

function setup(role: RoleName = 'inventory_officer', productOverrides = {}) {
  vi.spyOn(client, 'refreshAccessToken').mockResolvedValue({
    access_token: 't', token_type: 'bearer', expires_in: 900, user: makeUser(role),
  });
  const onDone = vi.fn();
  renderWithProviders(
    <AdjustStockModal open product={makeProduct({ avg_cost: '198.0000', ...productOverrides })} batches={[]} onClose={() => {}} onDone={onDone} />,
  );
  return { onDone };
}

describe('AdjustStockModal', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it('previews a count correction and submits the counted quantity', async () => {
    vi.mocked(stockApi.adjust).mockResolvedValue({ adjustment: {} as never, applied: true, message: 'Stock of White Sugar 2kg adjusted by -4 pcs.' });
    const { onDone } = setup();
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText(/counted quantity/i), '42');
    const preview = within(dialog).getByRole('status', { name: 'Adjustment preview' });
    expect(preview).toHaveTextContent(/Change\s*−4 pcs\s*→ new balance\s*42 pcs/);
    expect(preview).toHaveTextContent(/792\.00/); // 4 x KES 198 at cost
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save adjustment' }));
    expect(stockApi.adjust).toHaveBeenCalledWith(expect.objectContaining({ product_id: 7, counted_quantity: '42', reason_code: 'COUNT_CORRECTION' }));
    expect(onDone).toHaveBeenCalledWith('Stock of White Sugar 2kg adjusted by -4 pcs.', true);
  });

  it('rejects fractions for whole-unit products before calling the API', async () => {
    setup();
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText(/counted quantity/i), '41.5');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save adjustment' }));
    expect(await within(dialog).findByText(/counted in whole pcs/)).toBeInTheDocument();
    expect(stockApi.adjust).not.toHaveBeenCalled();
  });

  it('requires a note for suspected losses', async () => {
    setup();
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByText('Add or remove'));
    await userEvent.type(within(dialog).getByLabelText(/^quantity/i), '3');
    await userEvent.selectOptions(within(dialog).getByLabelText('Reason'), 'THEFT_SUSPECTED');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save adjustment' }));
    expect(await within(dialog).findByText('Please explain this adjustment')).toBeInTheDocument();
  });

  it('warns about negative stock and only offers the override to super admins', async () => {
    setup('inventory_officer');
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByText('Add or remove'));
    await userEvent.type(within(dialog).getByLabelText(/^quantity/i), '50');
    expect(within(dialog).getByText(/Only a Super Administrator/)).toBeInTheDocument();
    expect(within(dialog).queryByLabelText(/authorise negative stock/i)).not.toBeInTheDocument();
  });
});

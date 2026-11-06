import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { categoriesApi, suppliersApi } from '@/api/catalog';
import * as client from '@/api/client';
import { makeUser, renderWithProviders } from '@/test/utils';

import { ProductFormModal } from './ProductFormModal';

vi.mock('@/api/catalog', () => ({ categoriesApi: { list: vi.fn() }, suppliersApi: { list: vi.fn() } }));

describe('ProductFormModal', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(client, 'refreshAccessToken').mockResolvedValue({
      access_token: 't', token_type: 'bearer', expires_in: 900, user: makeUser('inventory_officer'),
    });
    vi.mocked(categoriesApi.list).mockResolvedValue([
      { id: 3, name: 'Dairy', description: null, parent_id: 1, is_active: true, product_count: 2, path: 'Food › Dairy' },
    ]);
    vi.mocked(suppliersApi.list).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100, pages: 1 });
  });

  it('builds the create request including opening stock with expiry', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<ProductFormModal open onClose={() => {}} onSave={onSave} />);
    const d = await screen.findByRole('dialog', { name: 'Add product' });
    await userEvent.type(within(d).getByLabelText(/^name/i), 'Fresh Milk 500ml');
    await within(d).findByRole('option', { name: 'Food › Dairy' });
    await userEvent.selectOptions(within(d).getByLabelText('Category'), '3');
    await userEvent.type(within(d).getByLabelText(/selling price/i), '65');
    await userEvent.click(within(d).getByLabelText(/track expiry dates/i));
    await userEvent.type(within(d).getByLabelText(/quantity \(pcs\)/i), '24');
    await userEvent.type(within(d).getByLabelText(/unit cost/i), '48');
    await userEvent.click(within(d).getByRole('button', { name: 'Add product' }));
    // Expiry is required once there is opening stock of a tracked product.
    expect(await within(d).findByText('Enter the expiry date')).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();

    await userEvent.type(within(d).getByLabelText(/^expiry date/i), '2026-11-12');
    await userEvent.click(within(d).getByRole('button', { name: 'Add product' }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      name: 'Fresh Milk 500ml', category_id: 3, selling_price: '65', vat_rate: '16', tracks_expiry: true,
      opening_stock: { quantity: '24', unit_cost: '48', expiry_date: '2026-11-12', batch_number: null },
    }));
  });

  it('validates prices and stock levels', async () => {
    renderWithProviders(<ProductFormModal open onClose={() => {}} onSave={vi.fn()} />);
    const d = await screen.findByRole('dialog', { name: 'Add product' });
    await userEvent.type(within(d).getByLabelText(/^name/i), 'Bread');
    await userEvent.type(within(d).getByLabelText(/selling price/i), '70.555');
    await userEvent.clear(within(d).getByLabelText(/^minimum/i));
    await userEvent.type(within(d).getByLabelText(/^minimum/i), '10');
    await userEvent.type(within(d).getByLabelText(/^maximum/i), '5');
    await userEvent.click(within(d).getByRole('button', { name: 'Add product' }));
    expect(await within(d).findByText('Enter an amount like 245 or 245.50')).toBeInTheDocument();
    expect(within(d).getByText('Must be at least the minimum')).toBeInTheDocument();
  });
});

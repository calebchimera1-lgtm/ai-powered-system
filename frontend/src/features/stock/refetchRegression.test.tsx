/**
 * Regression: background refetches hand dialogs fresh product/batch objects. That must not
 * wipe what the user has typed (it did before; found in end-to-end browser testing).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { categoriesApi, suppliersApi } from '@/api/catalog';
import * as client from '@/api/client';
import { AuthProvider } from '@/auth/AuthProvider';
import { ToastProvider } from '@/components/ui/Toast';
import { ProductFormModal } from '@/features/products/ProductFormModal';
import { makeProduct, makeUser } from '@/test/utils';

import { AdjustStockModal } from './AdjustStockModal';

vi.mock('@/api/catalog', () => ({ categoriesApi: { list: vi.fn() }, suppliersApi: { list: vi.fn() } }));
vi.mock('@/api/stock', () => ({ stockApi: { adjust: vi.fn() } }));

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
const wrap = (ui: ReactElement) => (
  <QueryClientProvider client={qc}>
    <ToastProvider>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AuthProvider>{ui}</AuthProvider>
      </MemoryRouter>
    </ToastProvider>
  </QueryClientProvider>
);

describe('dialogs survive background refetches', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(client, 'refreshAccessToken').mockResolvedValue({
      access_token: 't', token_type: 'bearer', expires_in: 900, user: makeUser('inventory_officer'),
    });
    vi.mocked(categoriesApi.list).mockResolvedValue([]);
    vi.mocked(suppliersApi.list).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100, pages: 1 });
  });

  it('adjust-stock input is kept when the product object is replaced', async () => {
    const props = { open: true, onClose: () => {}, onDone: () => {} };
    const { rerender } = render(wrap(<AdjustStockModal {...props} product={makeProduct()} batches={[]} />));
    const input = await screen.findByLabelText(/counted quantity/i);
    await userEvent.type(input, '42');
    rerender(wrap(<AdjustStockModal {...props} product={makeProduct({ barcode: '2000000000077' })} batches={[]} />));
    expect(screen.getByLabelText(/counted quantity/i)).toHaveValue('42');
  });

  it('product edit form keeps edits when the same product is refreshed', async () => {
    const props = { open: true, onClose: () => {}, onSave: vi.fn() };
    const { rerender } = render(wrap(<ProductFormModal {...props} product={makeProduct()} />));
    const dialog = await screen.findByRole('dialog');
    const price = within(dialog).getByLabelText(/selling price/i);
    await userEvent.clear(price);
    await userEvent.type(price, '260');
    rerender(wrap(<ProductFormModal {...props} product={makeProduct({ updated_at: '2026-11-06T10:00:00Z' })} />));
    expect(within(screen.getByRole('dialog')).getByLabelText(/selling price/i)).toHaveValue('260');
    // ...but opening a different product does load that product's values.
    rerender(wrap(<ProductFormModal {...props} product={makeProduct({ id: 99, selling_price: '75.00' })} />));
    expect(within(screen.getByRole('dialog')).getByLabelText(/selling price/i)).toHaveValue('75');
  });
});

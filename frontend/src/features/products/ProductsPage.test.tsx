import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { categoriesApi, productsApi } from '@/api/catalog';
import * as client from '@/api/client';
import { stockApi } from '@/api/stock';
import type { RoleName } from '@/api/types';
import { makeProduct, makeUser, renderWithProviders } from '@/test/utils';

import { ProductsPage } from './ProductsPage';

vi.mock('@/api/catalog', () => ({
  productsApi: { list: vi.fn(), lookup: vi.fn(), create: vi.fn() },
  categoriesApi: { list: vi.fn() },
  suppliersApi: { list: vi.fn() },
}));
vi.mock('@/api/stock', () => ({ stockApi: { summary: vi.fn() } }));

function setup(role: RoleName) {
  vi.spyOn(client, 'refreshAccessToken').mockResolvedValue({
    access_token: 't', token_type: 'bearer', expires_in: 900, user: makeUser(role),
  });
  vi.mocked(categoriesApi.list).mockResolvedValue([]);
  vi.mocked(stockApi.summary).mockResolvedValue({
    active_products: 10, out_of_stock: 1, low_stock: 2, expiring_soon: 1, expired_in_stock: 0,
    pending_adjustments: 1, inventory_value: '84210.50',
  });
  vi.mocked(productsApi.list).mockResolvedValue({
    items: [
      makeProduct({ avg_cost: '198.0000', margin_percent: '6.26' }),
      makeProduct({ id: 8, name: 'Bottled Water 1L', sku: 'WAT-1L', quantity_on_hand: '0.000', stock_status: 'out' }),
    ],
    total: 2, page: 1, page_size: 25, pages: 1,
  });
  return renderWithProviders(
    <Routes>
      <Route path="/products" element={<ProductsPage />} />
      <Route path="/products/:id" element={<p>Product detail screen</p>} />
    </Routes>,
    { route: '/products' },
  );
}

describe('ProductsPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it('shows stock levels, badges, summary tiles and margins for managers', async () => {
    setup('store_manager');
    expect(await screen.findByText('White Sugar 2kg')).toBeInTheDocument();
    // Rendered twice: in the stock column and (for phones) under the price.
    expect(screen.getAllByText('46 pcs')).toHaveLength(2);
    expect(screen.getAllByText('Out of stock')).toHaveLength(2);
    expect(screen.getByText('6.3%')).toBeInTheDocument();
    expect(await screen.findByText(/84,210\.50/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add product/i })).toBeInTheDocument();
  });

  it('cashiers get a read-only list without costs or stock summary', async () => {
    setup('cashier');
    await screen.findByText('White Sugar 2kg');
    expect(screen.queryByRole('columnheader', { name: 'Margin' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add product/i })).not.toBeInTheDocument();
    expect(stockApi.summary).not.toHaveBeenCalled();
  });

  it('pressing Enter on a scanned barcode opens the product', async () => {
    vi.mocked(productsApi.lookup).mockResolvedValue({ match: 'barcode', product: makeProduct() });
    setup('inventory_officer');
    const box = await screen.findByRole('searchbox', { name: 'Search products' });
    await userEvent.type(box, '2000000000015{Enter}');
    expect(await screen.findByText('Product detail screen')).toBeInTheDocument();
    expect(productsApi.lookup).toHaveBeenCalledWith('2000000000015');
  });

  it('filters by stock state', async () => {
    setup('inventory_officer');
    await screen.findByText('White Sugar 2kg');
    await userEvent.click(screen.getByRole('button', { name: 'Low' }));
    await waitFor(() =>
      expect(productsApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ stock: 'low', page: 1 })),
    );
  });
});

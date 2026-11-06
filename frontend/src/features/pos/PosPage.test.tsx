import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { productsApi } from '@/api/catalog';
import * as client from '@/api/client';
import { salesApi } from '@/api/sales';
import type { RoleName, Sale } from '@/api/types';
import { makeProduct, makeUser, renderWithProviders } from '@/test/utils';

import { newRequestId, PosPage } from './PosPage';

vi.mock('@/api/catalog', () => ({ productsApi: { list: vi.fn(), lookup: vi.fn() } }));
vi.mock('@/api/sales', () => ({ salesApi: { store: vi.fn(), checkout: vi.fn() } }));

const sugar = makeProduct({ id: 7, name: 'White Sugar 2kg', selling_price: '245.00', quantity_on_hand: '46.000' });
const bread = makeProduct({ id: 8, name: 'White Bread 400g', selling_price: '70.00', barcode: '2000000000060', quantity_on_hand: '3.000' });

function setup(role: RoleName = 'cashier') {
  vi.spyOn(client, 'refreshAccessToken').mockResolvedValue({ access_token: 't', token_type: 'bearer', expires_in: 900, user: makeUser(role) });
  vi.mocked(salesApi.store).mockResolvedValue({ name: 'Demo Store', address: 'Nairobi', phone: '', kra_pin: '', receipt_footer: 'Thanks', currency: 'KES', max_cashier_discount_percent: '10' });
  vi.mocked(productsApi.list).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 8, pages: 1 });
  vi.mocked(productsApi.lookup).mockImplementation(async (code) => {
    if (code === '2000000000015') return { match: 'barcode', product: sugar };
    if (code === '2000000000060') return { match: 'barcode', product: bread };
    throw new Error('not found');
  });
  return renderWithProviders(<PosPage />);
}

async function scan(code: string) {
  const box = await screen.findByRole('combobox', { name: 'Find product' });
  await userEvent.type(box, `${code}{Enter}`);
}

describe('PosPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it('scanning adds items, repeat scans increase quantity, totals and change update', async () => {
    setup();
    await scan('2000000000015');
    await scan('2000000000015');
    await scan('2000000000060');
    expect(screen.getByLabelText('Quantity of White Sugar 2kg')).toHaveValue('2');
    expect(screen.getByTestId('pos-total')).toHaveTextContent('KES 560.00');
    expect(screen.getByText('KES 77.25')).toBeInTheDocument(); // VAT included
    await userEvent.type(screen.getByLabelText('Cash received'), '1000');
    expect(screen.getByText('Change: KES 440.00')).toBeInTheDocument();
  });

  it('submits one request id with the cart and shows the receipt', async () => {
    const sale = { id: 1, receipt_number: 'RCPT-2026-000001', sold_at: '2026-11-06T10:00:00Z', status: 'COMPLETED', cashier: { id: 1, username: 'amina', full_name: 'Amina Wanjiru' }, customer: null, subtotal: '245.00', discount_total: '0.00', tax_total: '33.79', grand_total: '245.00', cost_total: null, gross_profit: null, payment_method: 'CASH', payment_reference: null, amount_tendered: '300.00', change_given: '55.00', notes: null, items: [{ id: 1, product_id: 7, product_name: 'White Sugar 2kg', quantity: '1.000', unit_price: '245.00', discount_amount: '0.00', vat_rate: '16.00', tax_amount: '33.79', line_total: '245.00', returned_quantity: '0.000', unit_cost: null }] } satisfies Sale;
    vi.mocked(salesApi.checkout).mockResolvedValue(sale);
    setup();
    await scan('2000000000015');
    await userEvent.type(screen.getByLabelText('Cash received'), '300');
    await userEvent.click(screen.getByRole('button', { name: /complete sale/i }));
    expect(salesApi.checkout).toHaveBeenCalledWith(expect.objectContaining({
      items: [{ product_id: 7, quantity: '1' }], payment_method: 'CASH', amount_tendered: '300.00',
      client_request_id: expect.stringMatching(/^[0-9a-f-]{36}$/),
    }));
    const dialog = await screen.findByRole('dialog', { name: 'Sale complete' });
    expect(within(dialog).getByText('Receipt: RCPT-2026-000001')).toBeInTheDocument();
    expect(within(dialog).getByText('Give change: KES 55.00')).toBeInTheDocument();
  });

  it('blocks checkout when short of cash, over stock, or over the discount limit', async () => {
    setup('cashier');
    await scan('2000000000060');
    const pay = screen.getByRole('button', { name: /complete sale/i });
    await userEvent.type(screen.getByLabelText('Cash received'), '50');
    expect(screen.getByText('Short by KES 20.00')).toBeInTheDocument();
    expect(pay).toBeDisabled();

    await userEvent.clear(screen.getByLabelText('Cash received'));
    await userEvent.type(screen.getByLabelText('Cash received'), '500');
    expect(pay).toBeEnabled();

    await userEvent.clear(screen.getByLabelText('Quantity of White Bread 400g'));
    await userEvent.type(screen.getByLabelText('Quantity of White Bread 400g'), '5');
    expect(screen.getByText('Only 3 pcs in stock')).toBeInTheDocument();
    expect(pay).toBeDisabled();

    await userEvent.clear(screen.getByLabelText('Quantity of White Bread 400g'));
    await userEvent.type(screen.getByLabelText('Quantity of White Bread 400g'), '1');
    await userEvent.type(screen.getByLabelText('Discount'), '20'); // 20 of 70 = 28%
    expect(screen.getByText('Discounts above 10% need a Store Manager.')).toBeInTheDocument();
    expect(pay).toBeDisabled();
  });

  it('M-Pesa needs a 10-character transaction code', async () => {
    setup();
    await scan('2000000000060');
    await userEvent.click(screen.getByRole('radio', { name: 'M-Pesa' }));
    const pay = screen.getByRole('button', { name: /complete sale/i });
    await userEvent.type(screen.getByLabelText('M-Pesa transaction code'), 'skd4h2');
    expect(pay).toBeDisabled();
    await userEvent.type(screen.getByLabelText('M-Pesa transaction code'), 'l9qx');
    expect(screen.getByLabelText('M-Pesa transaction code')).toHaveValue('SKD4H2L9QX');
    expect(pay).toBeEnabled();
  });
});

describe('newRequestId', () => {
  it('produces UUID v4 strings even without crypto.randomUUID (plain-http tills)', () => {
    const original = crypto.randomUUID;
    Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true });
    try {
      const id = newRequestId();
      expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
      expect(newRequestId()).not.toBe(id);
    } finally {
      Object.defineProperty(crypto, 'randomUUID', { value: original, configurable: true });
    }
  });
});

describe('fast scanning', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it('keeps what the cashier types while a scanned code is still being looked up', async () => {
    setup();
    let release: (v: { match: 'barcode'; product: typeof sugar }) => void = () => {};
    vi.mocked(productsApi.lookup).mockImplementationOnce(() => new Promise((r) => { release = r; }));
    const box = await screen.findByRole('combobox', { name: 'Find product' });
    await userEvent.type(box, '2000000000015{Enter}');
    await userEvent.clear(box);
    await userEvent.type(box, 'bre');
    release({ match: 'barcode', product: sugar });
    expect(await screen.findByLabelText('Quantity of White Sugar 2kg')).toHaveValue('1');
    expect(box).toHaveValue('bre');
  });
});

describe('scanner bursts', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it('two quick scans of the same item give quantity 2, not a garbled code', async () => {
    setup();
    const resolvers: (() => void)[] = [];
    vi.mocked(productsApi.lookup).mockImplementation(
      (code) => new Promise((r, reject) => resolvers.push(() => (code === '2000000000015' ? r({ match: 'barcode', product: sugar }) : reject(new Error('x'))))),
    );
    const box = await screen.findByRole('combobox', { name: 'Find product' });
    await userEvent.type(box, '2000000000015{Enter}');
    expect(box).toHaveValue(''); // cleared at once
    await userEvent.type(box, '2000000000015{Enter}');
    resolvers.forEach((r) => r());
    await waitFor(() => expect(screen.getByLabelText('Quantity of White Sugar 2kg')).toHaveValue('2'));
    expect(productsApi.lookup).toHaveBeenNthCalledWith(2, '2000000000015');
  });
});

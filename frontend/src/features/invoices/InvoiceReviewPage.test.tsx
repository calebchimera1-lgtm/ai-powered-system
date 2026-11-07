import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { suppliersApi } from '@/api/catalog';
import * as client from '@/api/client';
import { invoicesApi } from '@/api/invoices';
import { makeUser, renderWithProviders } from '@/test/utils';

import { makeInvoice } from './fixtures';
import { InvoiceReviewPage } from './InvoiceReviewPage';
import { checkFile } from './InvoicesPage';

vi.mock('@/api/invoices', () => ({
  invoicesApi: { get: vi.fn(), pageBlob: vi.fn(), save: vi.fn(), approve: vi.fn(), reject: vi.fn(), reprocess: vi.fn() },
}));
vi.mock('@/api/catalog', () => ({
  suppliersApi: { list: vi.fn() },
  productsApi: { list: vi.fn(), lookup: vi.fn() },
}));

function renderPage(role: 'inventory_officer' | 'cashier' = 'inventory_officer') {
  vi.spyOn(client, 'refreshAccessToken').mockResolvedValue({ access_token: 't', token_type: 'bearer', expires_in: 900, user: makeUser(role) });
  return renderWithProviders(
    <Routes><Route path="/purchasing/invoices/:id" element={<InvoiceReviewPage />} /></Routes>,
    { route: '/purchasing/invoices/5' },
  );
}

describe('InvoiceReviewPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:page');
    globalThis.URL.revokeObjectURL = vi.fn();
    vi.mocked(invoicesApi.pageBlob).mockResolvedValue(new Blob(['x'], { type: 'image/png' }));
    vi.mocked(suppliersApi.list).mockResolvedValue({ items: [{ id: 3, name: 'Nairobi Wholesale (Demo)' }], total: 1, page: 1, page_size: 100, pages: 1 } as never);
  });

  it('highlights unclear fields and requires the suggested product to be confirmed', async () => {
    vi.mocked(invoicesApi.get).mockResolvedValue(makeInvoice());
    renderPage();
    const number = await screen.findByLabelText(/invoice number/i);
    expect(number).toHaveValue('INV-1');
    expect(screen.getByText(/not read clearly/i)).toBeInTheDocument(); // confidence 0.62
    expect(await screen.findByRole('img', { name: /page 1/i })).toHaveAttribute('src', 'blob:page');
    expect(screen.getByText(/Suggested \(76%\)/)).toBeInTheDocument();
    const approve = screen.getByRole('button', { name: /approve and receive/i });
    expect(approve).toBeDisabled();
    expect(screen.getByText(/confirm the suggested product/i)).toBeInTheDocument();
    expect(screen.getByText(/matches the subtotal/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(approve).toBeEnabled();
  });

  it('saves the corrections, then approves', async () => {
    const inv = makeInvoice();
    vi.mocked(invoicesApi.get).mockResolvedValue(inv);
    vi.mocked(invoicesApi.save).mockResolvedValue(inv);
    vi.mocked(invoicesApi.approve).mockResolvedValue({ ...inv, status: 'APPROVED', purchase_id: 44 });
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm' }));
    const qty = screen.getByLabelText('Line 1 quantity');
    await userEvent.clear(qty);
    await userEvent.type(qty, '10');
    expect(screen.getByText(/but the line total says/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /approve and receive/i }));
    expect(await screen.findByText(/receive this delivery into stock/i)).toBeInTheDocument();
    const dialogButtons = screen.getAllByRole('button', { name: /approve and receive/i });
    await userEvent.click(dialogButtons.at(-1)!);
    await waitFor(() => expect(invoicesApi.approve).toHaveBeenCalledWith(5));
    const body = vi.mocked(invoicesApi.save).mock.calls[0]![1];
    expect(body.items[0]).toMatchObject({ id: 11, product_id: 1, quantity: '10', confirm_product: true });
    expect(await screen.findByText('View goods-received note')).toHaveAttribute('href', '/purchasing/receipts/44');
  });

  it('is read-only once approved', async () => {
    vi.mocked(invoicesApi.get).mockResolvedValue(makeInvoice({ status: 'APPROVED', purchase_id: 44 }));
    renderPage();
    expect(await screen.findByLabelText(/invoice number/i)).toBeDisabled();
    expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument();
  });

  it('shows progress while the document is being read', async () => {
    vi.mocked(invoicesApi.get).mockResolvedValue(makeInvoice({ status: 'PROCESSING', items: [] }));
    renderPage();
    expect(await screen.findByText('Reading…')).toBeInTheDocument();
  });
});

describe('upload pre-check', () => {
  const file = (type: string, size: number) => new File([new Uint8Array(size)], 'x', { type });
  it('accepts photos and PDFs up to 10 MB only', () => {
    expect(checkFile(file('image/jpeg', 100))).toBeNull();
    expect(checkFile(file('application/pdf', 100))).toBeNull();
    expect(checkFile(file('text/plain', 100))).toMatch(/photo/);
    expect(checkFile(file('image/png', 11 * 1024 * 1024))).toMatch(/10 MB/);
    expect(checkFile(file('image/png', 0))).toMatch(/empty/);
  });
});

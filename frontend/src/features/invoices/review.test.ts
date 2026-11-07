import { describe, expect, it } from 'vitest';

import { makeInvoice, milk } from './fixtures';
import { approvalProblems, costExclVat, draftFrom, lineAmount, toReviewInput, totalsCheck } from './review';

describe('invoice review helpers', () => {
  it('builds a draft with readable numbers and sends suggestions unconfirmed', () => {
    const d = draftFrom(makeInvoice());
    expect(d.lines[0]!).toMatchObject({ quantity: '12', unit_price: '245', suggested: true });
    const body = toReviewInput(d);
    expect(body.items[0]).toMatchObject({ id: 11, product_id: 1, quantity: '12', unit_price: '245', confirm_product: false });
    expect(body.supplier_id).toBe(3);
    d.lines[0]!.suggested = false;
    expect(toReviewInput(d).items[0]!.confirm_product).toBe(true);
  });

  it('lists what blocks approval', () => {
    const d = draftFrom(makeInvoice());
    expect(approvalProblems(d)).toEqual(['Line 1: confirm the suggested product.']);
    d.lines[0] = { ...d.lines[0]!, suggested: false, product: milk, quantity: '' };
    d.invoice_number = ' ';
    expect(approvalProblems(d)).toEqual([
      'Enter the invoice number.', 'Line 1: enter the quantity.', 'Line 1: enter the expiry date.',
    ]);
  });

  it('checks the lines against the subtotal, or the total when prices include VAT', () => {
    const d = draftFrom(makeInvoice());
    expect(totalsCheck(d)).toMatchObject({ sum: 2940, expected: 2940, expectedLabel: 'Subtotal', matches: true });
    d.lines[0]!.line_total = '2900';
    expect(totalsCheck(d).matches).toBe(false);
    d.prices_include_vat = true;
    d.grand_total = '2900';
    expect(totalsCheck(d)).toMatchObject({ expectedLabel: 'Total', matches: true });
  });

  it('computes amounts and the VAT-exclusive stock cost', () => {
    const d = draftFrom(makeInvoice());
    expect(lineAmount(d.lines[0]!)).toBe(2940);
    expect(costExclVat(d.lines[0]!, false)).toBe(245);
    expect(costExclVat({ ...d.lines[0]!, unit_price: '116' }, true)).toBe(100);
    expect(costExclVat({ ...d.lines[0]!, product: milk, unit_price: '55' }, true)).toBe(55);
  });
});

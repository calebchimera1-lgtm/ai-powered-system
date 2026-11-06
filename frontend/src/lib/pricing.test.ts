import { describe, expect, it } from 'vitest';

import { priceCart } from './pricing';

// Same cases and hand-computed values as backend tests/unit/test_pricing.py.
describe('priceCart', () => {
  it('extracts VAT from inclusive prices', () => {
    const c = priceCart([
      { quantity: 2, unitPrice: 245, vatRate: 16 },
      { quantity: 1, unitPrice: 70, vatRate: 16 },
    ]);
    expect(c.total).toBe(560);
    expect(c.lines.map((l) => l.vat)).toEqual([67.59, 9.66]);
    expect(c.vat).toBe(77.25);
  });

  it('spreads a cart discount proportionally', () => {
    const c = priceCart(
      [
        { quantity: 2, unitPrice: 245, vatRate: 16, lineDiscount: 10 },
        { quantity: 1, unitPrice: 70, vatRate: 16 },
      ],
      55,
    );
    expect(c.lines.map((l) => l.discount)).toEqual([58, 7]);
    expect(c.total).toBe(495);
    expect(c.discount).toBe(65);
  });

  it('puts the rounding remainder on the largest line', () => {
    const c = priceCart([1, 2, 3].map(() => ({ quantity: 1, unitPrice: 100, vatRate: 16 })), 10);
    expect(c.lines.map((l) => l.discount).sort()).toEqual([3.33, 3.33, 3.34]);
    expect(c.total).toBe(290);
  });

  it('handles weighed goods', () => {
    expect(priceCart([{ quantity: 1.25, unitPrice: 125, vatRate: 16 }]).total).toBe(156.25);
  });
});

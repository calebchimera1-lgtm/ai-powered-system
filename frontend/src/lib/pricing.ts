/**
 * Live till totals, mirroring backend app/services/pricing.py so the screen matches the
 * receipt. The server recalculates everything; this is only for display.
 * Amounts are handled in integer cents to avoid floating-point drift.
 */

export interface PriceLine {
  quantity: number;
  unitPrice: number; // VAT-inclusive
  vatRate: number;
  lineDiscount?: number;
}

export interface PricedCart {
  subtotal: number;
  discount: number;
  vat: number;
  total: number;
  lines: { total: number; vat: number; discount: number }[];
}

const toCents = (n: number) => Math.round(n * 100);
// Half-up rounding like Python's ROUND_HALF_UP for positive values.
const roundHalfUp = (n: number) => Math.sign(n) * Math.round(Math.abs(n) + Number.EPSILON);

function vatCents(totalCents: number, rate: number): number {
  if (rate <= 0) return 0;
  return roundHalfUp((totalCents * rate) / (100 + rate));
}

export function priceCart(lines: PriceLine[], cartDiscount = 0): PricedCart {
  const gross = lines.map((l) => roundHalfUp(l.quantity * l.unitPrice * 100));
  const afterLine = lines.map((l, i) => gross[i]! - toCents(l.lineDiscount ?? 0));
  const base = afterLine.reduce((a, b) => a + b, 0);
  const cartCents = Math.min(toCents(cartDiscount), Math.max(base, 0));
  const shares = afterLine.map((v) => (base > 0 ? roundHalfUp((cartCents * v) / base) : 0));
  const remainder = cartCents - shares.reduce((a, b) => a + b, 0);
  if (remainder !== 0 && base > 0) {
    let largest = 0;
    afterLine.forEach((v, i) => {
      if (v > afterLine[largest]!) largest = i;
    });
    shares[largest]! += remainder;
  }
  const out = lines.map((l, i) => {
    const total = afterLine[i]! - shares[i]!;
    return { total: total / 100, vat: vatCents(total, l.vatRate) / 100, discount: (toCents(l.lineDiscount ?? 0) + shares[i]!) / 100 };
  });
  const subtotal = gross.reduce((a, b) => a + b, 0);
  const total = out.reduce((a, l) => a + toCents(l.total), 0);
  return {
    subtotal: subtotal / 100,
    discount: (subtotal - total) / 100,
    vat: out.reduce((a, l) => a + toCents(l.vat), 0) / 100,
    total: total / 100,
    lines: out,
  };
}

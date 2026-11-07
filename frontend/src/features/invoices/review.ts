/** Pure helpers for the invoice review screen (kept apart so they can be unit tested). */
import type { Invoice, InvoiceItem, InvoiceProduct, InvoiceStatus, ReviewInput } from '@/api/invoices';

export interface DraftLine {
  key: string;
  id: number | null;
  description: string;
  item_code: string | null;
  product: InvoiceProduct | null;
  /** The matcher proposed this product; the reviewer has not confirmed it yet. */
  suggested: boolean;
  match_method: string;
  match_score: number | null;
  confidence: number;
  quantity: string;
  unit_price: string;
  line_total: string;
  batch_number: string;
  expiry_date: string;
  raw_text: string | null;
}

export interface Draft {
  supplier_id: string;
  invoice_number: string;
  invoice_date: string;
  subtotal: string;
  tax_total: string;
  grand_total: string;
  prices_include_vat: boolean;
  lines: DraftLine[];
}

const s = (v: string | number | null | undefined) => (v === null || v === undefined ? '' : String(v));
/** "120.5000" -> "120.5", "24.000" -> "24": easier to read and edit. */
export const trim = (v: string | null | undefined) => (v ? String(Number(v)) : '');

let counter = 0;
export function lineFromItem(i: InvoiceItem): DraftLine {
  return {
    key: `i${i.id}`,
    id: i.id,
    description: i.description,
    item_code: i.item_code,
    product: i.product,
    suggested: i.suggested,
    match_method: i.match_method,
    match_score: i.match_score,
    confidence: i.confidence,
    quantity: trim(i.quantity),
    unit_price: trim(i.unit_price),
    line_total: s(i.line_total),
    batch_number: s(i.batch_number),
    expiry_date: s(i.expiry_date),
    raw_text: i.raw_text,
  };
}

export function blankLine(): DraftLine {
  counter += 1;
  return {
    key: `n${counter}`, id: null, description: '', item_code: null, product: null, suggested: false,
    match_method: 'MANUAL', match_score: null, confidence: 1, quantity: '', unit_price: '',
    line_total: '', batch_number: '', expiry_date: '', raw_text: null,
  };
}

export function draftFrom(inv: Invoice): Draft {
  return {
    supplier_id: inv.supplier ? String(inv.supplier.id) : '',
    invoice_number: s(inv.invoice_number),
    invoice_date: s(inv.invoice_date),
    subtotal: s(inv.subtotal),
    tax_total: s(inv.tax_total),
    grand_total: s(inv.grand_total),
    prices_include_vat: inv.prices_include_vat,
    lines: inv.items.map(lineFromItem),
  };
}

const orNull = (v: string) => (v.trim() === '' ? null : v.trim());

export function toReviewInput(d: Draft): ReviewInput {
  return {
    supplier_id: d.supplier_id ? Number(d.supplier_id) : null,
    invoice_number: orNull(d.invoice_number),
    invoice_date: orNull(d.invoice_date),
    subtotal: orNull(d.subtotal),
    tax_total: orNull(d.tax_total),
    grand_total: orNull(d.grand_total),
    prices_include_vat: d.prices_include_vat,
    items: d.lines.map((l) => ({
      id: l.id,
      description: l.description.trim() || l.product?.name || 'Item',
      product_id: l.product?.id ?? null,
      quantity: orNull(l.quantity),
      unit_price: orNull(l.unit_price),
      line_total: orNull(l.line_total),
      batch_number: orNull(l.batch_number),
      expiry_date: orNull(l.expiry_date),
      confirm_product: !l.suggested,
    })),
  };
}

const n = (v: string) => (v.trim() === '' ? null : Number(v));
const money = (v: number) => Math.round(v * 100) / 100;

/** qty x price, or null when either is missing. */
export function lineAmount(l: DraftLine): number | null {
  const q = n(l.quantity);
  const p = n(l.unit_price);
  return q === null || p === null || Number.isNaN(q) || Number.isNaN(p) ? null : money(q * p);
}

/** Supplier cost per unit before VAT, as it will be recorded in stock. */
export function costExclVat(l: DraftLine, pricesIncludeVat: boolean): number | null {
  const p = n(l.unit_price);
  if (p === null || Number.isNaN(p)) return null;
  if (!pricesIncludeVat || !l.product) return p;
  const rate = Number(l.product.vat_rate);
  return Math.round((p * 100 * 10000) / (100 + rate)) / 10000;
}

export interface Check {
  sum: number;
  /** What the lines should add up to (subtotal, or the total when prices include VAT). */
  expected: number | null;
  expectedLabel: string;
  matches: boolean | null;
}

/** Do the lines add up to the printed subtotal (or total, for VAT-inclusive prices)? */
export function totalsCheck(d: Draft): Check {
  const sum = money(d.lines.reduce((acc, l) => acc + (n(l.line_total) ?? lineAmount(l) ?? 0), 0));
  const expected = d.prices_include_vat ? n(d.grand_total) : n(d.subtotal) ?? n(d.grand_total);
  const expectedLabel = d.prices_include_vat || n(d.subtotal) === null ? 'Total' : 'Subtotal';
  return { sum, expected, expectedLabel, matches: expected === null ? null : Math.abs(sum - expected) <= 1 };
}

/** What still blocks approval, in plain words (the server checks the same and more). */
export function approvalProblems(d: Draft): string[] {
  const out: string[] = [];
  if (!d.supplier_id) out.push('Choose the supplier.');
  if (!d.invoice_number.trim()) out.push('Enter the invoice number.');
  if (d.lines.length === 0) out.push('Add at least one line.');
  d.lines.forEach((l, i) => {
    const label = `Line ${i + 1}`;
    if (!l.product) out.push(`${label}: choose the product.`);
    else if (l.suggested) out.push(`${label}: confirm the suggested product.`);
    const q = n(l.quantity);
    if (q === null || Number.isNaN(q) || q <= 0) out.push(`${label}: enter the quantity.`);
    const p = n(l.unit_price);
    if (p === null || Number.isNaN(p) || p < 0) out.push(`${label}: enter the unit price.`);
    if (l.product?.tracks_expiry && !l.expiry_date) out.push(`${label}: enter the expiry date.`);
  });
  return out;
}

/** Below this the field is highlighted for the reviewer to check. */
export const LOW_CONFIDENCE = 0.85;

export const STATUS_LABEL: Record<InvoiceStatus, string> = {
  QUEUED: 'Waiting to be read',
  PROCESSING: 'Reading…',
  NEEDS_REVIEW: 'Needs review',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  FAILED: 'Could not read',
};

export const STATUS_TONE: Record<InvoiceStatus, 'green' | 'gray' | 'red' | 'amber' | 'blue'> = {
  QUEUED: 'gray',
  PROCESSING: 'blue',
  NEEDS_REVIEW: 'amber',
  APPROVED: 'green',
  REJECTED: 'gray',
  FAILED: 'red',
};

export const MATCH_LABEL: Record<string, string> = {
  CODE: 'Matched by code',
  ALIAS: 'Matched from earlier invoices',
  FUZZY: 'Matched by name',
  MANUAL: 'Chosen by hand',
  NONE: 'Not matched',
};

export const isWorking = (s: InvoiceStatus) => s === 'QUEUED' || s === 'PROCESSING';

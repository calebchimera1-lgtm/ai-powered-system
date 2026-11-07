/** Test data for the invoice screens. */
import type { Invoice } from '@/api/invoices';

export const sugar = { id: 1, name: 'White Sugar 2kg', sku: 'SKU-1', unit_of_measure: 'pcs', tracks_expiry: false, vat_rate: '16.00' };
export const milk = { id: 2, name: 'Fresh Milk 500ml', sku: 'SKU-2', unit_of_measure: 'pcs', tracks_expiry: true, vat_rate: '0.00' };

export function makeInvoice(overrides: Partial<Invoice> = {}): Invoice {
  return {
    id: 5, status: 'NEEDS_REVIEW', original_filename: 'delivery.jpg', mime_type: 'image/jpeg', file_size: 1000,
    page_count: 1, uploaded_by: { id: 1, username: 'amina', full_name: 'Amina Wanjiru' }, created_at: '2026-11-07T08:00:00Z',
    ocr_engine: 'tesseract', processing_ms: 900, processing_steps: ['paper outline found; perspective corrected'],
    quality: { score: 1, problems: [], skew_degrees: 0, document_detected: true }, error_message: null,
    supplier: { id: 3, name: 'Nairobi Wholesale (Demo)' }, supplier_match_score: 100, extracted_supplier_name: 'NAIROBI WHOLESALE',
    kra_pin: 'P051111111A', invoice_number: 'INV-1', invoice_date: '2026-11-05', subtotal: '2940.00', tax_total: '470.40',
    grand_total: '3410.40', prices_include_vat: false,
    field_confidences: { supplier: 1, invoice_number: 0.62, invoice_date: 0.95, subtotal: 0.95, tax_total: 0.95, grand_total: 0.95 },
    flags: [], reviewed_by: null, reviewed_at: null, review_note: null, purchase_id: null,
    items: [
      { id: 11, line_no: 1, raw_text: 'WHT SUGAR 2KG 12 245.00 2,940.00', description: 'WHT SUGAR 2KG', item_code: null,
        quantity: '12.000', unit_price: '245.0000', line_total: '2940.00', product: sugar, match_method: 'FUZZY',
        match_score: 76, suggested: true, confidence: 0.93, arithmetic_ok: true, batch_number: null, expiry_date: null, was_corrected: false },
    ],
    ...overrides,
  };
}

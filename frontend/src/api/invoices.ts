import { api } from './client';
import type { Page, UserBrief } from './types';

type Decimal = string;

export type InvoiceStatus = 'QUEUED' | 'PROCESSING' | 'NEEDS_REVIEW' | 'APPROVED' | 'REJECTED' | 'FAILED';
export type MatchMethod = 'CODE' | 'ALIAS' | 'FUZZY' | 'MANUAL' | 'NONE';

export interface InvoiceFlag {
  code: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
  item?: number | null;
}

export interface InvoiceProduct {
  id: number;
  name: string;
  sku: string;
  unit_of_measure: string;
  tracks_expiry: boolean;
  vat_rate: Decimal;
  purchase_price?: Decimal | null;
}

export interface InvoiceItem {
  id: number;
  line_no: number;
  raw_text: string | null;
  description: string;
  item_code: string | null;
  quantity: Decimal | null;
  unit_price: Decimal | null;
  line_total: Decimal | null;
  product: InvoiceProduct | null;
  match_method: MatchMethod;
  match_score: number | null;
  suggested: boolean;
  confidence: number;
  arithmetic_ok: boolean;
  batch_number: string | null;
  expiry_date: string | null;
  was_corrected: boolean;
}

export interface Invoice {
  id: number;
  status: InvoiceStatus;
  original_filename: string;
  mime_type: string;
  file_size: number;
  page_count: number;
  uploaded_by: UserBrief;
  created_at: string;
  ocr_engine: string | null;
  processing_ms: number | null;
  processing_steps: string[] | null;
  quality: { score: number; problems: string[]; skew_degrees: number; document_detected: boolean } | null;
  error_message: string | null;
  supplier: { id: number; name: string } | null;
  supplier_match_score: number | null;
  extracted_supplier_name: string | null;
  kra_pin: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  subtotal: Decimal | null;
  tax_total: Decimal | null;
  grand_total: Decimal | null;
  prices_include_vat: boolean;
  field_confidences: Record<string, number> | null;
  flags: InvoiceFlag[] | null;
  reviewed_by: UserBrief | null;
  reviewed_at: string | null;
  review_note: string | null;
  purchase_id: number | null;
  items: InvoiceItem[];
}

export interface InvoiceSummary {
  id: number;
  status: InvoiceStatus;
  original_filename: string;
  created_at: string;
  uploaded_by: UserBrief;
  supplier: { id: number; name: string } | null;
  extracted_supplier_name: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  grand_total: Decimal | null;
  purchase_id: number | null;
  line_count: number;
  warnings: number;
}

export interface InvoiceStats {
  by_status: Partial<Record<InvoiceStatus, number>>;
  approved: number;
  approved_lines: number;
  lines_corrected: number;
  line_correction_rate: number | null;
  waiting_over_24h: number;
}

export interface ReviewLineInput {
  id?: number | null;
  description: string;
  product_id: number | null;
  quantity: string | null;
  unit_price: string | null;
  line_total: string | null;
  batch_number?: string | null;
  expiry_date?: string | null;
  confirm_product: boolean;
}

export interface ReviewInput {
  supplier_id: number | null;
  invoice_number: string | null;
  invoice_date: string | null;
  subtotal: string | null;
  tax_total: string | null;
  grand_total: string | null;
  prices_include_vat: boolean;
  items: ReviewLineInput[];
}

export const invoicesApi = {
  list: (q: { page?: number; page_size?: number; status?: string }) =>
    api
      .get<Page<InvoiceSummary>>('/invoices', { params: Object.fromEntries(Object.entries(q).filter(([, v]) => v)) })
      .then((r) => r.data),
  stats: () => api.get<InvoiceStats>('/invoices/stats').then((r) => r.data),
  get: (id: number) => api.get<Invoice>(`/invoices/${id}`).then((r) => r.data),
  upload: (file: File, onProgress?: (pct: number) => void) => {
    const form = new FormData();
    form.append('file', file);
    return api
      .post<Invoice>('/invoices', form, {
        timeout: 120_000,
        onUploadProgress: (e) => e.total && onProgress?.(Math.round((e.loaded / e.total) * 100)),
      })
      .then((r) => r.data);
  },
  /** The page image is private: fetched with the access token, shown via an object URL. */
  pageBlob: (id: number, page: number) =>
    api.get<Blob>(`/invoices/${id}/pages/${page}`, { responseType: 'blob' }).then((r) => r.data),
  save: (id: number, body: ReviewInput) => api.put<Invoice>(`/invoices/${id}`, body).then((r) => r.data),
  approve: (id: number, note?: string) =>
    api.post<Invoice>(`/invoices/${id}/approve`, { note: note || null }).then((r) => r.data),
  reject: (id: number, note: string) => api.post<Invoice>(`/invoices/${id}/reject`, { note }).then((r) => r.data),
  reprocess: (id: number) => api.post<Invoice>(`/invoices/${id}/reprocess`).then((r) => r.data),
};

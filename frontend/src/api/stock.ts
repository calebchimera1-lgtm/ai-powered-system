import { api } from './client';
import type { Adjustment, AdjustmentReason, Movement, Page, StockSummary } from './types';

export interface MovementParams {
  page?: number;
  page_size?: number;
  product_id?: number;
  movement_type?: string;
  user_id?: number;
  date_from?: string;
  date_to?: string;
}

export interface AdjustmentInput {
  product_id: number;
  counted_quantity?: string;
  quantity_change?: string;
  reason_code: AdjustmentReason;
  notes?: string | null;
  batch_id?: number | null;
  expiry_date?: string | null;
  allow_negative?: boolean;
}

function clean<T extends object>(params: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''),
  ) as Partial<T>;
}

export const stockApi = {
  summary: () => api.get<StockSummary>('/stock/summary').then((r) => r.data),
  movements: (p: MovementParams) =>
    api.get<Page<Movement>>('/stock/movements', { params: clean(p) }).then((r) => r.data),
  adjustments: (p: { page?: number; page_size?: number; status?: string; product_id?: number }) =>
    api.get<Page<Adjustment>>('/stock/adjustments', { params: clean(p) }).then((r) => r.data),
  adjust: (body: AdjustmentInput) =>
    api
      .post<{ adjustment: Adjustment; applied: boolean; message: string }>('/stock/adjustments', body)
      .then((r) => r.data),
  approve: (id: number, note?: string, allow_negative = false) =>
    api.post<Adjustment>(`/stock/adjustments/${id}/approve`, { note, allow_negative }).then((r) => r.data),
  reject: (id: number, note: string) =>
    api.post<Adjustment>(`/stock/adjustments/${id}/reject`, { note }).then((r) => r.data),
  writeOff: (body: {
    product_id: number;
    quantity: string;
    kind: 'DAMAGED' | 'EXPIRED';
    batch_id?: number | null;
    notes?: string | null;
  }) =>
    api
      .post<{ movements: Movement[]; quantity_on_hand: string; value_lost: string | null }>(
        '/stock/write-offs',
        body,
      )
      .then((r) => r.data),
};

import { api } from './client';
import type { Page, PaymentMethod, Sale, SaleReturn, SalesSummary, StoreInfo } from './types';

function clean<T extends object>(params: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''),
  ) as Partial<T>;
}

export interface CheckoutInput {
  client_request_id: string;
  items: { product_id: number; quantity: string; discount?: string }[];
  cart_discount?: string;
  payment_method: PaymentMethod;
  amount_tendered?: string | null;
  payment_reference?: string | null;
  customer_name?: string | null;
  customer_phone?: string | null;
}

export interface SalesQuery {
  page?: number;
  page_size?: number;
  date_from?: string;
  date_to?: string;
  cashier_id?: number;
  payment_method?: string;
  search?: string;
}

export const salesApi = {
  store: () => api.get<StoreInfo>('/store').then((r) => r.data),
  checkout: (body: CheckoutInput) => api.post<Sale>('/sales', body).then((r) => r.data),
  list: (q: SalesQuery) => api.get<Page<Sale>>('/sales', { params: clean(q) }).then((r) => r.data),
  summary: (q: { date_from?: string; date_to?: string; cashier_id?: number }) =>
    api.get<SalesSummary>('/sales/summary', { params: clean(q) }).then((r) => r.data),
  get: (id: number) => api.get<Sale>(`/sales/${id}`).then((r) => r.data),
  byReceipt: (no: string) =>
    api.get<Sale>(`/sales/by-receipt/${encodeURIComponent(no.trim())}`).then((r) => r.data),
  createReturn: (
    saleId: number,
    body: {
      items: { sale_item_id: number; quantity: string; condition: 'RESALEABLE' | 'DAMAGED' }[];
      reason: string;
      refund_method: PaymentMethod;
    },
  ) => api.post<SaleReturn>(`/sales/${saleId}/returns`, body).then((r) => r.data),
  returns: (q: { page?: number; page_size?: number; status?: string; sale_id?: number }) =>
    api.get<Page<SaleReturn>>('/returns', { params: clean(q) }).then((r) => r.data),
  approveReturn: (id: number, note?: string) =>
    api.post<SaleReturn>(`/returns/${id}/approve`, { note }).then((r) => r.data),
  rejectReturn: (id: number, note: string) =>
    api.post<SaleReturn>(`/returns/${id}/reject`, { note }).then((r) => r.data),
};

import { api } from './client';
import type { Page, Purchase, PurchaseOrder } from './types';

function clean<T extends object>(params: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''),
  ) as Partial<T>;
}

export interface POInput {
  supplier_id: number;
  expected_date?: string | null;
  notes?: string | null;
  items: { product_id: number; quantity: string; unit_cost: string }[];
}

export interface GRNInput {
  supplier_id: number;
  purchase_order_id?: number | null;
  supplier_invoice_number?: string | null;
  invoice_date?: string | null;
  notes?: string | null;
  items: {
    product_id: number;
    quantity: string;
    unit_cost: string;
    vat_rate?: string | null;
    batch_number?: string | null;
    expiry_date?: string | null;
  }[];
}

export const purchasingApi = {
  orders: (q: { page?: number; page_size?: number; status?: string; supplier_id?: number }) =>
    api.get<Page<PurchaseOrder>>('/purchase-orders', { params: clean(q) }).then((r) => r.data),
  order: (id: number) => api.get<PurchaseOrder>(`/purchase-orders/${id}`).then((r) => r.data),
  createOrder: (body: POInput) => api.post<PurchaseOrder>('/purchase-orders', body).then((r) => r.data),
  updateOrder: (id: number, body: POInput) =>
    api.put<PurchaseOrder>(`/purchase-orders/${id}`, body).then((r) => r.data),
  sendOrder: (id: number) => api.post<PurchaseOrder>(`/purchase-orders/${id}/send`).then((r) => r.data),
  cancelOrder: (id: number, reason?: string) =>
    api.post<PurchaseOrder>(`/purchase-orders/${id}/cancel`, { reason }).then((r) => r.data),
  receipts: (q: { page?: number; page_size?: number; supplier_id?: number; search?: string }) =>
    api.get<Page<Purchase>>('/purchases', { params: clean(q) }).then((r) => r.data),
  receipt: (id: number) => api.get<Purchase>(`/purchases/${id}`).then((r) => r.data),
  receive: (body: GRNInput) => api.post<Purchase>('/purchases', body).then((r) => r.data),
};

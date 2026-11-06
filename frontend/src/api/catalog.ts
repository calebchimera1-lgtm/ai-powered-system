import { api } from './client';
import type {
  Batch,
  Category,
  Message,
  Page,
  Product,
  Supplier,
  SupplierProduct,
  Unit,
} from './types';

function clean<T extends object>(params: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''),
  ) as Partial<T>;
}

export interface ProductListParams {
  page?: number;
  page_size?: number;
  search?: string;
  category_id?: number;
  supplier_id?: number;
  stock?: 'out' | 'low' | 'ok' | 'over' | 'expiring';
  status?: 'active' | 'inactive' | 'all';
  sort?: 'name' | '-updated' | 'quantity' | 'sku';
}

export interface ProductInput {
  name: string;
  description?: string | null;
  sku?: string | null;
  barcode?: string | null;
  category_id?: number | null;
  default_supplier_id?: number | null;
  unit_of_measure: Unit;
  selling_price: string;
  purchase_price?: string;
  vat_rate: string;
  min_stock_level: string;
  max_stock_level?: string | null;
  reorder_lead_time_days: number;
  tracks_expiry: boolean;
  is_active?: boolean;
  opening_stock?: {
    quantity: string;
    unit_cost: string;
    expiry_date?: string | null;
    batch_number?: string | null;
  } | null;
}

export const productsApi = {
  list: (p: ProductListParams) =>
    api.get<Page<Product>>('/products', { params: clean(p) }).then((r) => r.data),
  get: (id: number) => api.get<Product>(`/products/${id}`).then((r) => r.data),
  lookup: (code: string) =>
    api
      .get<{ match: 'barcode' | 'sku'; product: Product }>('/products/lookup', { params: { code } })
      .then((r) => r.data),
  create: (body: ProductInput) => api.post<Product>('/products', body).then((r) => r.data),
  update: (id: number, body: Partial<ProductInput>) =>
    api.patch<Product>(`/products/${id}`, body).then((r) => r.data),
  remove: (id: number) => api.delete<Message>(`/products/${id}`).then((r) => r.data),
  generateBarcode: (id: number) =>
    api.post<Product>(`/products/${id}/barcode`).then((r) => r.data),
  /** Fetched with the auth header, returned as an object URL for <img>. */
  barcodeSvgUrl: async (id: number) => {
    const r = await api.get<Blob>(`/products/${id}/barcode.svg`, { responseType: 'blob' });
    return URL.createObjectURL(r.data);
  },
  uploadImage: (id: number, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return api.post<Product>(`/products/${id}/image`, form).then((r) => r.data);
  },
  removeImage: (id: number) => api.delete<Product>(`/products/${id}/image`).then((r) => r.data),
  batches: (id: number, includeEmpty = false) =>
    api
      .get<Batch[]>(`/products/${id}/batches`, { params: { include_empty: includeEmpty } })
      .then((r) => r.data),
  suppliers: (id: number) =>
    api.get<SupplierProduct[]>(`/products/${id}/suppliers`).then((r) => r.data),
};

export interface CategoryInput {
  name: string;
  description?: string | null;
  parent_id?: number | null;
  is_active?: boolean;
}

export const categoriesApi = {
  list: (includeInactive = false) =>
    api
      .get<Category[]>('/categories', { params: { include_inactive: includeInactive } })
      .then((r) => r.data),
  create: (body: CategoryInput) => api.post<Category>('/categories', body).then((r) => r.data),
  update: (id: number, body: Partial<CategoryInput>) =>
    api.patch<Category>(`/categories/${id}`, body).then((r) => r.data),
  remove: (id: number) => api.delete<Message>(`/categories/${id}`).then((r) => r.data),
};

export interface SupplierInput {
  name: string;
  kra_pin?: string | null;
  contact_person?: string | null;
  phone?: string | null;
  email?: string | null;
  address?: string | null;
  payment_terms_days: number;
  notes?: string | null;
  is_active?: boolean;
}

export const suppliersApi = {
  list: (p: { page?: number; page_size?: number; search?: string; is_active?: boolean }) =>
    api.get<Page<Supplier>>('/suppliers', { params: clean(p) }).then((r) => r.data),
  get: (id: number) => api.get<Supplier>(`/suppliers/${id}`).then((r) => r.data),
  create: (body: SupplierInput) => api.post<Supplier>('/suppliers', body).then((r) => r.data),
  update: (id: number, body: Partial<SupplierInput>) =>
    api.patch<Supplier>(`/suppliers/${id}`, body).then((r) => r.data),
  products: (id: number) =>
    api.get<SupplierProduct[]>(`/suppliers/${id}/products`).then((r) => r.data),
  linkProduct: (
    id: number,
    productId: number,
    body: { supplier_sku?: string | null; last_unit_price?: string | null; lead_time_days?: number | null },
  ) => api.put<SupplierProduct>(`/suppliers/${id}/products/${productId}`, body).then((r) => r.data),
  unlinkProduct: (id: number, productId: number) =>
    api.delete<Message>(`/suppliers/${id}/products/${productId}`).then((r) => r.data),
};

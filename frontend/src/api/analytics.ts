import { api } from './client';
import type { Page, UserBrief } from './types';

type Decimal = string;

export interface ProductRef {
  id: number;
  name: string;
  sku: string;
  unit_of_measure: string;
  default_supplier_id?: number | null;
}

export interface ForecastRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: 'RUNNING' | 'SUCCEEDED' | 'FAILED';
  history_start: string | null;
  history_end: string | null;
  horizon_days: number;
  params: Record<string, unknown> | null;
  summary: {
    products?: number;
    low_confidence?: number;
    chosen_models?: Record<string, number>;
    mean_mase_by_model?: Record<string, number>;
    beats_seasonal_naive?: number;
    compared_with_seasonal_naive?: number;
    seconds?: number;
  } | null;
  error_message: string | null;
}

export interface ProductForecast {
  product: ProductRef;
  model_name: string;
  model_label: string;
  low_confidence: boolean;
  history_days: number;
  avg_daily_28: number;
  demand_pattern: string | null;
  adi: number | null;
  cv2: number | null;
  abc_class: string | null;
  revenue_90d: Decimal | null;
  weekday_profile: number[] | null;
  payday_effect: number | null;
  on_hand: Decimal;
  on_order: Decimal;
  lead_time_days: number;
  stockout_date: string | null;
  days_of_cover: number | null;
  safety_stock: number;
  reorder_point: number;
  should_order: boolean;
  suggested_quantity: Decimal;
  residual_std: number;
  next_7_days: number;
  next_28_days: number;
  chosen_mase: number | null;
  seasonal_naive_mase: number | null;
}

export interface ForecastOverview {
  run: ForecastRun | null;
  running: boolean;
  products: ProductForecast[];
}

export interface ModelScore {
  model: string;
  label: string;
  origins: number;
  mae: number;
  rmse: number;
  mape: number | null;
  smape: number | null;
  mase: number | null;
  rmsse: number | null;
}

export interface SeriesPoint {
  date: string;
  actual: number | null;
  forecast: number | null;
  lower: number | null;
  upper: number | null;
}

export interface ProductForecastDetail {
  run: ForecastRun;
  forecast: ProductForecast;
  scores: ModelScore[];
  series: SeriesPoint[];
}

export interface ReorderLine {
  product: ProductRef;
  on_hand: Decimal;
  on_order: Decimal;
  reorder_point: number;
  stockout_date: string | null;
  lead_time_days: number;
  suggested_quantity: Decimal;
  unit_cost: Decimal | null;
  line_value: Decimal | null;
}

export interface ReorderGroup {
  supplier_id: number | null;
  supplier_name: string;
  lines: ReorderLine[];
  total_value: Decimal;
}

export type AlertStatus = 'OPEN' | 'INVESTIGATING' | 'RESOLVED_ISSUE_FOUND' | 'RESOLVED_NO_ISSUE';
export type Severity = 'LOW' | 'MEDIUM' | 'HIGH';

export interface Evidence {
  day: string;
  detector: string;
  score: number;
  explanation: string;
  figures: Record<string, { value: number; normal: number; z: number }>;
}

export interface AnomalyAlert {
  id: number;
  entity_type: 'product' | 'user';
  product: ProductRef | null;
  subject_user: UserBrief | null;
  kind: string;
  kind_label: string;
  detected_at: string;
  period_start: string;
  period_end: string;
  quantity: number;
  value_kes: Decimal;
  severity: Severity;
  score: number;
  detector: 'RULE' | 'ISOLATION_FOREST' | 'BOTH';
  explanation: string;
  recommended_action: string;
  evidence: Evidence[] | null;
  status: AlertStatus;
  reviewed_by: UserBrief | null;
  reviewed_at: string | null;
  review_notes: string | null;
}

export interface AnomalyStats {
  by_status: Partial<Record<AlertStatus, number>>;
  open_by_severity: Partial<Record<Severity, number>>;
  open_value_kes: Decimal;
  reviewed: number;
  precision: number | null;
}

export interface AppNotification {
  id: number;
  type: string;
  title: string;
  message: string;
  link: string | null;
  severity: 'info' | 'warning' | 'critical';
  is_read: boolean;
  created_at: string;
}

export interface NotificationPage {
  items: AppNotification[];
  total: number;
  unread: number;
}

const clean = (q: Record<string, unknown>) =>
  Object.fromEntries(Object.entries(q).filter(([, v]) => v !== undefined && v !== null && v !== ''));

export const forecastsApi = {
  overview: () => api.get<ForecastOverview>('/forecasts').then((r) => r.data),
  run: () => api.post<{ job_id: number; message: string }>('/forecasts/run').then((r) => r.data),
  product: (id: number) => api.get<ProductForecastDetail>(`/forecasts/products/${id}`).then((r) => r.data),
  reorder: () => api.get<ReorderGroup[]>('/forecasts/reorder').then((r) => r.data),
};

export const anomaliesApi = {
  list: (q: { status?: string; severity?: string; page?: number; page_size?: number }) =>
    api.get<Page<AnomalyAlert>>('/anomalies', { params: clean(q) }).then((r) => r.data),
  stats: () => api.get<AnomalyStats>('/anomalies/stats').then((r) => r.data),
  get: (id: number) => api.get<AnomalyAlert>(`/anomalies/${id}`).then((r) => r.data),
  review: (id: number, status: AlertStatus, notes: string) =>
    api.post<AnomalyAlert>(`/anomalies/${id}/review`, { status, notes: notes || null }).then((r) => r.data),
  scan: () => api.post<{ job_id: number; message: string }>('/anomalies/scan').then((r) => r.data),
};

export const notificationsApi = {
  list: (q: { unread?: boolean; limit?: number; offset?: number }) =>
    api.get<NotificationPage>('/notifications', { params: clean(q) }).then((r) => r.data),
  unreadCount: () => api.get<{ unread: number }>('/notifications/unread-count').then((r) => r.data.unread),
  markRead: (ids?: number[]) => api.post<{ updated: number }>('/notifications/read', { ids: ids ?? null }).then((r) => r.data),
};

// --- Dashboard -------------------------------------------------------------------------

export interface Dashboard {
  date_from: string;
  date_to: string;
  category_id: number | null;
  inventory: {
    total_products: number;
    out_of_stock: number;
    low_stock: number;
    low_stock_items: { product_id: number; name: string; on_hand: Decimal; min_stock: Decimal; unit: string }[];
    expiring_soon: number;
    expiring_items: { product_id: number; name: string; expiry_date: string; quantity: Decimal; unit: string; expired: boolean }[];
    inventory_value: Decimal | null;
  };
  movers: {
    fast: Mover[];
    slow: Mover[];
  };
  shortages: { product_id: number; name: string; stockout_date: string; lead_time_days: number; suggested_quantity: Decimal; unit: string }[];
  approvals: {
    invoices_to_review: number;
    purchase_orders_draft: number;
    purchase_orders_open: number;
    adjustments_pending: number;
    returns_pending: number;
  };
  sales: {
    today_revenue: Decimal;
    today_transactions: number;
    month_revenue: Decimal;
    month_gross_profit: Decimal;
    period_revenue: Decimal;
    period_gross_profit: Decimal;
    period_transactions: number;
    gross_margin_percent: Decimal | null;
    trend: { day: string; revenue: Decimal; gross_profit: Decimal }[];
  } | null;
  categories: { category: string; revenue: Decimal; gross_profit: Decimal }[] | null;
  open_irregularities: number | null;
}

export interface Mover {
  product_id: number;
  name: string;
  unit: string;
  per_day: number;
  on_hand: Decimal;
  days_of_cover: number | null;
}

export const dashboardApi = {
  get: (q: { date_from?: string; date_to?: string; category_id?: number | null }) =>
    api.get<Dashboard>('/dashboard', { params: clean(q) }).then((r) => r.data),
};

// --- Reports ---------------------------------------------------------------------------

export interface ReportType {
  key: string;
  title: string;
  description: string;
  uses_period: boolean;
  formats: ('pdf' | 'xlsx' | 'csv')[];
}

export const reportsApi = {
  list: () => api.get<ReportType[]>('/reports').then((r) => r.data),
  /** Download a report file; returns its name. Errors come back as JSON inside a Blob. */
  download: async (key: string, q: { format: string; date_from?: string; date_to?: string; category_id?: number | null }) => {
    try {
      const r = await api.get<Blob>(`/reports/${key}`, { params: clean(q), responseType: 'blob', timeout: 120_000 });
      const name = /filename="([^"]+)"/.exec(String(r.headers['content-disposition'] ?? ''))?.[1] ?? `${key}.${q.format}`;
      const url = URL.createObjectURL(r.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
      return name;
    } catch (e) {
      const data = (e as { response?: { data?: unknown } }).response?.data;
      if (data instanceof Blob) {
        try {
          (e as { response: { data: unknown } }).response.data = JSON.parse(await data.text());
        } catch {
          /* not JSON: keep the original error */
        }
      }
      throw e;
    }
  },
};

// --- Backups ---------------------------------------------------------------------------

export interface Backup {
  name: string;
  kind: 'daily' | 'manual';
  created_at: string;
  schema_revision: string;
  row_counts: Record<string, number>;
  files: Record<string, { bytes: number; sha256: string }>;
  verified: boolean;
  total_bytes: number;
}

export interface BackupListing {
  backups: Backup[];
  running: boolean;
  last_error: string | null;
  policy: { daily: number; weekly: number; manual: number };
}

export const backupsApi = {
  list: () => api.get<BackupListing>('/system/backups').then((r) => r.data),
  create: () => api.post<{ job_id: number; message: string }>('/system/backups').then((r) => r.data),
  download: async (name: string, file: string) => {
    const r = await api.get<Blob>(`/system/backups/${name}/${file}`, { responseType: 'blob', timeout: 300_000 });
    const url = URL.createObjectURL(r.data);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${name}-${file}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
  },
};

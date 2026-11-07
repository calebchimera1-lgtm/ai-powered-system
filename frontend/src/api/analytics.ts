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

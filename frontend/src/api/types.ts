// Types mirroring the backend Pydantic schemas (app/schemas/*).

export interface RoleBrief {
  id: number;
  name: RoleName;
  display_name: string;
}

export type RoleName = 'super_admin' | 'store_manager' | 'inventory_officer' | 'cashier';

export interface CurrentUser {
  id: number;
  full_name: string;
  username: string;
  email: string;
  phone: string | null;
  role: RoleBrief;
  permissions: string[];
  must_change_password: boolean;
  last_login_at: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  user: CurrentUser;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface UserOut {
  id: number;
  full_name: string;
  username: string;
  email: string;
  phone: string | null;
  role: RoleBrief;
  is_active: boolean;
  must_change_password: boolean;
  is_locked: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface UserCreated {
  user: UserOut;
  setup_url: string | null;
  setup_expires_at: string | null;
}

export interface PasswordResetIssued {
  reset_url: string;
  expires_at: string;
}

export interface PermissionOut {
  code: string;
  description: string;
}

export interface RoleOut {
  id: number;
  name: RoleName;
  display_name: string;
  description: string;
  permissions: PermissionOut[];
  user_count: number;
}

export interface SessionOut {
  id: number;
  user_agent: string | null;
  ip_address: string | null;
  created_at: string;
  last_used_at: string;
  expires_at: string;
  is_current: boolean;
}

export interface AuditLogOut {
  id: number;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  details: string | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
  user: { id: number; username: string; full_name: string } | null;
}

export interface Message {
  message: string;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: { field: string; message: string }[] | null;
  };
}

// --- Phase 2: catalogue and stock ------------------------------------------------
// Decimals arrive as strings ("1250.00") so no precision is lost.

export type Decimal = string;
export type Unit = 'pcs' | 'pack' | 'box' | 'dozen' | 'bottle' | 'carton' | 'bag' | 'kg' | 'g' | 'l' | 'ml';
export type StockStatus = 'out' | 'low' | 'ok' | 'over';

export interface Category {
  id: number;
  name: string;
  description: string | null;
  parent_id: number | null;
  is_active: boolean;
  product_count: number;
  path: string;
}

export interface Product {
  id: number;
  sku: string;
  barcode: string | null;
  name: string;
  description: string | null;
  category: { id: number; name: string } | null;
  default_supplier: { id: number; name: string } | null;
  unit_of_measure: Unit;
  image_url: string | null;
  selling_price: Decimal;
  vat_rate: Decimal;
  quantity_on_hand: Decimal;
  min_stock_level: Decimal;
  max_stock_level: Decimal | null;
  reorder_lead_time_days: number;
  tracks_expiry: boolean;
  is_active: boolean;
  stock_status: StockStatus;
  next_expiry: string | null;
  created_at: string;
  updated_at: string;
  // Only present for roles that may see costs:
  purchase_price?: Decimal;
  avg_cost?: Decimal;
  stock_value?: Decimal;
  margin_percent?: Decimal | null;
}

export interface Batch {
  id: number;
  batch_number: string | null;
  expiry_date: string | null;
  quantity_received: Decimal;
  quantity_remaining: Decimal;
  unit_cost: Decimal | null;
  received_at: string;
  days_to_expiry: number | null;
}

export interface Supplier {
  id: number;
  name: string;
  kra_pin: string | null;
  contact_person: string | null;
  phone: string | null;
  email: string | null;
  address: string | null;
  payment_terms_days: number;
  notes: string | null;
  is_active: boolean;
  product_count: number;
  created_at: string;
}

export interface SupplierProduct {
  supplier_id: number;
  supplier_name: string;
  product_id: number;
  product_name: string;
  product_sku: string;
  supplier_sku: string | null;
  last_unit_price: Decimal | null;
  lead_time_days: number | null;
  updated_at: string;
}

export type MovementType =
  | 'OPENING'
  | 'PURCHASE_IN'
  | 'RETURN_IN'
  | 'ADJUSTMENT_IN'
  | 'SALE_OUT'
  | 'RETURN_TO_SUPPLIER'
  | 'DAMAGED'
  | 'EXPIRED'
  | 'ADJUSTMENT_OUT';

export interface UserBrief {
  id: number;
  username: string;
  full_name: string;
}

export interface ProductRef {
  id: number;
  sku: string;
  name: string;
  unit_of_measure: Unit;
}

export interface Movement {
  id: number;
  product: ProductRef;
  batch_id: number | null;
  batch_number: string | null;
  movement_type: MovementType;
  quantity: Decimal;
  unit_cost: Decimal | null;
  value: Decimal | null;
  balance_after: Decimal;
  reference_type: string | null;
  reference_id: string | null;
  reason: string | null;
  user: UserBrief;
  created_at: string;
}

export type AdjustmentReason =
  | 'COUNT_CORRECTION'
  | 'FOUND_STOCK'
  | 'DATA_ENTRY_ERROR'
  | 'THEFT_SUSPECTED'
  | 'INTERNAL_USE'
  | 'OTHER';

export interface Adjustment {
  id: number;
  product: ProductRef;
  reason_code: AdjustmentReason;
  notes: string | null;
  system_quantity: Decimal;
  counted_quantity: Decimal | null;
  quantity_change: Decimal;
  value_impact: Decimal | null;
  allow_negative: boolean;
  status: 'PENDING' | 'APPROVED' | 'REJECTED';
  requested_by: UserBrief;
  decided_by: UserBrief | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
}

export interface StockSummary {
  active_products: number;
  out_of_stock: number;
  low_stock: number;
  expiring_soon: number;
  expired_in_stock: number;
  pending_adjustments: number;
  inventory_value: Decimal | null;
}

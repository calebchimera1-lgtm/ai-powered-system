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
  mfa_enabled?: boolean;
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
  mfa_enabled?: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface MfaSetup {
  secret: string;
  otpauth_uri: string;
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
    details?: { field: string; message: string }[] | Record<string, unknown> | null;
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
  /** 160 px WebP for lists and small previews. */
  thumbnail_url?: string | null;
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

// --- Phase 3: sales, returns, purchasing, finance ---------------------------------

export type PaymentMethod = 'CASH' | 'MPESA' | 'CARD';

export interface SaleItem {
  id: number;
  product_id: number;
  product_name: string;
  quantity: Decimal;
  unit_price: Decimal;
  discount_amount: Decimal;
  vat_rate: Decimal;
  tax_amount: Decimal;
  line_total: Decimal;
  returned_quantity: Decimal;
  unit_cost: Decimal | null;
}

export interface Sale {
  id: number;
  receipt_number: string;
  sold_at: string;
  status: 'COMPLETED' | 'PARTIALLY_RETURNED' | 'RETURNED';
  cashier: UserBrief;
  customer: { id: number; name: string; phone: string | null } | null;
  subtotal: Decimal;
  discount_total: Decimal;
  tax_total: Decimal;
  grand_total: Decimal;
  cost_total: Decimal | null;
  gross_profit: Decimal | null;
  payment_method: PaymentMethod;
  payment_reference: string | null;
  amount_tendered: Decimal | null;
  change_given: Decimal | null;
  notes: string | null;
  items: SaleItem[];
}

export interface SalesSummary {
  count: number;
  gross_total: Decimal;
  discount_total: Decimal;
  tax_total: Decimal;
  refunds_total: Decimal;
  by_method: { payment_method: PaymentMethod; count: number; total: Decimal }[];
}

export interface StoreInfo {
  name: string;
  address: string;
  phone: string;
  kra_pin: string;
  receipt_footer: string;
  currency: string;
  max_cashier_discount_percent: Decimal;
}

export interface SaleReturn {
  id: number;
  return_number: string;
  sale_id: number;
  receipt_number: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED';
  reason: string;
  refund_method: PaymentMethod;
  refund_total: Decimal;
  requested_by: UserBrief;
  decided_by: UserBrief | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
  items: {
    id: number;
    sale_item_id: number;
    product_id: number;
    product_name: string;
    quantity: Decimal;
    refund_amount: Decimal;
    condition: 'RESALEABLE' | 'DAMAGED';
  }[];
}

export interface POProduct {
  id: number;
  sku: string;
  name: string;
  unit_of_measure: Unit;
  tracks_expiry: boolean;
  vat_rate: Decimal;
}

export type POStatus = 'DRAFT' | 'SENT' | 'PARTIAL' | 'RECEIVED' | 'CANCELLED';

export interface PurchaseOrder {
  id: number;
  po_number: string;
  supplier: { id: number; name: string };
  status: POStatus;
  order_date: string;
  expected_date: string | null;
  notes: string | null;
  created_by: UserBrief;
  sent_at: string | null;
  created_at: string;
  total: Decimal;
  items: {
    id: number;
    product: POProduct;
    quantity_ordered: Decimal;
    quantity_received: Decimal;
    unit_cost: Decimal;
  }[];
}

export interface PriceChange {
  product_id: number;
  product_name: string;
  previous_unit_cost: Decimal;
  new_unit_cost: Decimal;
  change_percent: Decimal;
}

export interface Purchase {
  id: number;
  grn_number: string;
  supplier: { id: number; name: string };
  purchase_order_id: number | null;
  po_number: string | null;
  supplier_invoice_number: string | null;
  invoice_date: string | null;
  received_at: string;
  subtotal: Decimal;
  tax_total: Decimal;
  grand_total: Decimal;
  source: 'MANUAL' | 'INVOICE';
  notes: string | null;
  received_by: UserBrief;
  price_changes: PriceChange[];
  items: {
    id: number;
    product: POProduct;
    quantity: Decimal;
    unit_cost: Decimal;
    vat_rate: Decimal;
    tax_amount: Decimal;
    line_total: Decimal;
    previous_unit_cost: Decimal | null;
    batch_number: string | null;
    expiry_date: string | null;
  }[];
}

export interface ExpenseCategory {
  id: number;
  name: string;
  is_active: boolean;
}

export interface Expense {
  id: number;
  category: ExpenseCategory;
  expense_date: string;
  amount: Decimal;
  description: string;
  payment_method: PaymentMethod | 'BANK';
  reference: string | null;
  recorded_by: UserBrief;
  created_at: string;
}

export interface FinancialSummary {
  date_from: string;
  date_to: string;
  transactions: number;
  items_sold: Decimal;
  sales_gross: Decimal;
  vat_collected: Decimal;
  refunds_gross: Decimal;
  revenue: Decimal;
  cost_of_goods_sold: Decimal;
  gross_profit: Decimal;
  gross_margin_percent: Decimal | null;
  stock_losses: Decimal;
  net_adjustments: Decimal;
  operating_expenses: Decimal;
  net_profit_estimate: Decimal;
  purchases_total: Decimal;
  average_basket: Decimal | null;
  discounts_given: Decimal;
}

export interface AnalyticsOverview {
  summary: FinancialSummary;
  daily: { day: string; revenue: Decimal; cost_of_goods_sold: Decimal; gross_profit: Decimal; transactions: number }[];
  by_category: { category: string; quantity: Decimal; revenue: Decimal; cost_of_goods_sold: Decimal; gross_profit: Decimal; margin_percent: Decimal | null }[];
  top_products: { product_id: number; name: string; sku: string; category: string | null; quantity: Decimal; revenue: Decimal; cost_of_goods_sold: Decimal; gross_profit: Decimal; margin_percent: Decimal | null }[];
  payment_methods: { payment_method: PaymentMethod; transactions: number; total: Decimal }[];
}

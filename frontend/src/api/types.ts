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

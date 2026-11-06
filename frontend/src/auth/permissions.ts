// Permission codes, mirroring backend app/core/permissions.py.
// The UI uses them only to hide controls; the server enforces every check.
export const PERM = {
  USERS_READ: 'users:read',
  USERS_MANAGE: 'users:manage',
  ROLES_READ: 'roles:read',
  AUDIT_READ: 'audit:read',
  PRODUCTS_READ: 'products:read',
  PRODUCTS_WRITE: 'products:write',
  PRODUCTS_DELETE: 'products:delete',
  PRODUCTS_VIEW_COST: 'products:view_cost',
  STOCK_READ: 'stock:read',
  STOCK_ADJUST: 'stock:adjust',
  STOCK_ADJUST_APPROVE: 'stock:adjust_approve',
  STOCK_ADJUST_NEGATIVE: 'stock:adjust_negative',
  STOCK_WRITE_OFF: 'stock:write_off',
  SUPPLIERS_READ: 'suppliers:read',
  SUPPLIERS_WRITE: 'suppliers:write',
} as const;

export type PermissionCode = (typeof PERM)[keyof typeof PERM] | (string & {});

// Permission codes, mirroring backend app/core/permissions.py.
// The UI uses them only to hide controls; the server enforces every check.
export const PERM = {
  USERS_READ: 'users:read',
  USERS_MANAGE: 'users:manage',
  ROLES_READ: 'roles:read',
  AUDIT_READ: 'audit:read',
} as const;

export type PermissionCode = (typeof PERM)[keyof typeof PERM] | (string & {});

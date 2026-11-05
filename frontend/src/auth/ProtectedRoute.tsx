import type { ReactNode } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';

import { FullPageSpinner } from '@/components/ui/Spinner';
import { EmptyState } from '@/components/ui/EmptyState';

import { useAuth } from './AuthProvider';
import type { PermissionCode } from './permissions';

/** Requires a signed-in user; forces the temporary-password change first. */
export function RequireAuth() {
  const { status, user } = useAuth();
  const location = useLocation();

  if (status === 'loading') return <FullPageSpinner label="Loading your session…" />;
  if (status === 'anonymous' || !user) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  if (user.must_change_password && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />;
  }
  return <Outlet />;
}

/** Shows a friendly message instead of the page when the user lacks the permission. */
export function RequirePermission({
  anyOf,
  children,
}: {
  anyOf: PermissionCode[];
  children: ReactNode;
}) {
  const { canAny } = useAuth();
  if (!canAny(...anyOf)) {
    return (
      <EmptyState
        title="You don't have access to this page"
        description="Ask a Super Administrator if you need access."
      />
    );
  }
  return <>{children}</>;
}

/** Only renders children when the user has the permission (for buttons, links). */
export function Can({ perm, children }: { perm: PermissionCode; children: ReactNode }) {
  const { can } = useAuth();
  return can(perm) ? <>{children}</> : null;
}

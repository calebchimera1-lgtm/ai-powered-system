import type { ReactNode } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';

import { FullPageSpinner } from '@/components/ui/Spinner';
import { EmptyState } from '@/components/ui/EmptyState';
import { usePageTitle } from '@/hooks/usePageTitle';

import { useAuth } from './AuthProvider';
import type { PermissionCode } from './permissions';

/** Requires a signed-in user; forces the temporary-password change first. */
export function RequireAuth() {
  const { status, user, signedOut } = useAuth();
  const location = useLocation();

  if (status === 'loading') return <FullPageSpinner label="Loading your session…" />;
  if (status === 'anonymous' || !user) {
    // After a deliberate sign-out the next person starts at Home, not on the previous
    // user's page. Otherwise (deep link, expired session) return them where they were.
    const state = signedOut ? undefined : { from: location.pathname + location.search };
    return <Navigate to="/login" replace state={state} />;
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
  if (!canAny(...anyOf)) return <NoAccess />;
  return <>{children}</>;
}

function NoAccess() {
  usePageTitle('No access');
  return (
    <>
      <h1 className="sr-only">No access</h1>
      <EmptyState
        title="You don't have access to this page"
        description="Ask a Super Administrator if you need access."
      />
    </>
  );
}

/** Only renders children when the user has the permission (for buttons, links). */
export function Can({ perm, children }: { perm: PermissionCode; children: ReactNode }) {
  const { can } = useAuth();
  return can(perm) ? <>{children}</> : null;
}

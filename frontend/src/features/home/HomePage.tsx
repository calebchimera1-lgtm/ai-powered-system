import { ArrowRight, ShieldCheck } from 'lucide-react';
import { Link } from 'react-router-dom';

import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { DashboardPage } from '@/features/dashboard/DashboardPage';
import { Card, PageHeader } from '@/components/ui/Card';
import { visibleSections } from '@/components/layout/navigation';
import { formatDateTime } from '@/lib/format';

function greeting(): string {
  const hour = Number(
    new Intl.DateTimeFormat('en-KE', { hour: 'numeric', hour12: false, timeZone: 'Africa/Nairobi' }).format(new Date()),
  );
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  return 'Good evening';
}

export function HomePage() {
  const { user, canAny, can } = useAuth();
  if (!user) return null;
  if (can(PERM.DASHBOARD_READ)) return <DashboardPage greeting={greeting()} />;
  const shortcuts = visibleSections(canAny)
    .flatMap((s) => s.items)
    .filter((i) => i.to !== '/');

  return (
    <>
      <PageHeader
        documentTitle="Home"
        title={`${greeting()}, ${user.full_name.split(' ')[0]}`}
        description={`Signed in as ${user.role.display_name} since ${formatDateTime(user.last_login_at)}.`}
      />
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="md:col-span-2" title="Quick links">
          <ul className="grid gap-3 sm:grid-cols-2">
            {shortcuts.map(({ to, label, icon: Icon }) => (
              <li key={to}>
                <Link
                  to={to}
                  className="group flex items-center gap-3 rounded-lg border border-gray-200 p-3 hover:border-brand-300 hover:bg-brand-50/50"
                >
                  <span className="rounded-lg bg-brand-50 p-2 text-brand-700">
                    <Icon className="h-5 w-5" aria-hidden />
                  </span>
                  <span className="flex-1 text-sm font-medium text-gray-800">{label}</span>
                  <ArrowRight className="h-4 w-4 text-gray-300 group-hover:text-brand-600" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Your access">
          <div className="flex items-start gap-3">
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" aria-hidden />
            <p className="text-sm text-gray-600">
              Your role, <span className="font-medium text-gray-900">{user.role.display_name}</span>, grants{' '}
              {user.permissions.length} permissions. Menus only show what you can use.
            </p>
          </div>
        </Card>
      </div>
    </>
  );
}

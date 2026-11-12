import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Monitor } from 'lucide-react';
import { useState, type ReactNode } from 'react';

import { authApi } from '@/api/auth';
import type { SessionOut } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmailLink, PhoneLink } from '@/components/ui/ContactLink';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { ChangePasswordForm } from '@/features/auth/ChangePasswordForm';
import { errorMessage } from '@/lib/errors';
import { describeUserAgent, formatDateTime } from '@/lib/format';

function Detail({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</dt>
      <dd className="mt-0.5 break-words text-sm text-gray-900">{value}</dd>
    </div>
  );
}

export function AccountPage() {
  const { user } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [revoking, setRevoking] = useState<SessionOut | null>(null);

  const sessions = useQuery({ queryKey: ['my-sessions'], queryFn: authApi.sessions });
  const revoke = useMutation({
    mutationFn: (id: number) => authApi.revokeSession(id),
    onSuccess: () => {
      toast.success('Device signed out');
      setRevoking(null);
      qc.invalidateQueries({ queryKey: ['my-sessions'] });
    },
    onError: (err) => toast.error('Could not sign out device', errorMessage(err)),
  });

  if (!user) return null;

  return (
    <>
      <PageHeader title="My account" description="Your profile, password and signed-in devices." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Profile" description="Ask an administrator to change these details.">
          <dl className="grid gap-4 sm:grid-cols-2">
            <Detail label="Full name" value={user.full_name} />
            <Detail label="Username" value={user.username} />
            <Detail label="Email" value={<EmailLink email={user.email} />} />
            <Detail label="Phone" value={user.phone ? <PhoneLink phone={user.phone} /> : '—'} />
            <Detail label="Role" value={user.role.display_name} />
            <Detail label="Signed in at" value={formatDateTime(user.last_login_at)} />
          </dl>
        </Card>

        <Card title="Change password" description="Your other devices will be signed out.">
          <ChangePasswordForm
            onDone={() => {
              toast.success('Password changed', 'Other devices have been signed out.');
              qc.invalidateQueries({ queryKey: ['my-sessions'] });
            }}
          />
        </Card>

        <Card className="lg:col-span-2" title="Signed-in devices" description="Sign out any device you don't recognise.">
          {sessions.isLoading && <Spinner label="Loading…" />}
          {sessions.isError && <Alert tone="error">{errorMessage(sessions.error)}</Alert>}
          <ul className="divide-y divide-gray-100">
            {sessions.data?.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-3 py-3">
                <Monitor className="h-5 w-5 shrink-0 text-gray-400" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900">
                    {describeUserAgent(s.user_agent)} {s.is_current && <Badge tone="green">This device</Badge>}
                  </p>
                  <p className="text-xs text-gray-500">
                    IP {s.ip_address ?? 'unknown'} · signed in {formatDateTime(s.created_at)} · last active{' '}
                    {formatDateTime(s.last_used_at)}
                  </p>
                </div>
                {!s.is_current && (
                  <Button size="sm" variant="secondary" onClick={() => setRevoking(s)}>
                    Sign out
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <ConfirmDialog
        open={Boolean(revoking)}
        title="Sign out this device?"
        message={revoking ? `${describeUserAgent(revoking.user_agent)} will need to sign in again.` : ''}
        confirmLabel="Sign out device"
        loading={revoke.isPending}
        onConfirm={() => revoking && revoke.mutate(revoking.id)}
        onCancel={() => setRevoking(null)}
      />
    </>
  );
}

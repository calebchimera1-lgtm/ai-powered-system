import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { KeyRound, LogOut, Pencil, Search, Unlock, UserCheck, UserPlus, UserX } from 'lucide-react';
import { useState } from 'react';

import type { UserOut } from '@/api/types';
import { usersApi, type UserCreateInput } from '@/api/users';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { ActionMenu } from '@/components/ui/ActionMenu';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { DataTable, Pagination, type Column } from '@/components/ui/DataTable';
import { useToast } from '@/components/ui/Toast';
import { useDebounce } from '@/hooks/useDebounce';
import { errorMessage } from '@/lib/errors';
import { formatDateTime } from '@/lib/format';

import { LinkModal } from './LinkModal';
import { UserFormModal, type CreateValues, type EditValues } from './UserFormModal';

const PAGE_SIZE = 20;

type Confirm =
  | { kind: 'deactivate' | 'activate' | 'signout'; user: UserOut }
  | null;

export function UsersPage() {
  const { user: me, can } = useAuth();
  const canManage = can(PERM.USERS_MANAGE);
  const toast = useToast();
  const qc = useQueryClient();

  const [search, setSearch] = useState('');
  const [role, setRole] = useState('');
  const [status, setStatus] = useState<'' | 'active' | 'inactive'>('');
  const [page, setPage] = useState(1);
  const debouncedSearch = useDebounce(search);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<UserOut | null>(null);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [link, setLink] = useState<{ title: string; name: string; url: string; expiresAt: string } | null>(null);

  const rolesQuery = useQuery({ queryKey: ['roles'], queryFn: usersApi.roles, staleTime: 5 * 60_000 });
  const usersQuery = useQuery({
    queryKey: ['users', { search: debouncedSearch, role, status, page }],
    queryFn: () =>
      usersApi.list({
        search: debouncedSearch,
        role,
        is_active: status === '' ? undefined : status === 'active',
        page,
        page_size: PAGE_SIZE,
      }),
    placeholderData: keepPreviousData,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ['users'] });

  const actionMutation = useMutation({
    mutationFn: async (c: NonNullable<Confirm>) => {
      if (c.kind === 'signout') return (await usersApi.revokeSessions(c.user.id)).message;
      await usersApi.update(c.user.id, { is_active: c.kind === 'activate' });
      return c.kind === 'activate' ? `${c.user.full_name} can sign in again` : `${c.user.full_name} was deactivated`;
    },
    onSuccess: (message) => {
      toast.success(message);
      setConfirm(null);
      invalidate();
    },
    onError: (err) => toast.error('Action failed', errorMessage(err)),
  });

  const resetLink = async (u: UserOut) => {
    try {
      const r = await usersApi.issueReset(u.id);
      setLink({ title: 'Password reset link', name: u.full_name, url: r.reset_url, expiresAt: r.expires_at });
    } catch (err) {
      toast.error('Could not create reset link', errorMessage(err));
    }
  };

  const unlock = async (u: UserOut) => {
    try {
      await usersApi.unlock(u.id);
      toast.success(`${u.full_name} is unlocked`);
      invalidate();
    } catch (err) {
      toast.error('Could not unlock', errorMessage(err));
    }
  };

  const submitForm = async (values: CreateValues | EditValues) => {
    if (editing) {
      const v = values as EditValues;
      await usersApi.update(editing.id, {
        full_name: v.full_name,
        email: v.email,
        phone: v.phone || null,
        ...(editing.id !== me?.id ? { role: v.role } : {}),
      });
      toast.success('Changes saved');
    } else {
      const v = values as CreateValues;
      const body: UserCreateInput = {
        full_name: v.full_name,
        username: v.username,
        email: v.email,
        phone: v.phone || null,
        role: v.role,
        password: v.passwordMode === 'set' ? v.password : null,
      };
      const created = await usersApi.create(body);
      toast.success(`Account created for ${created.user.full_name}`);
      if (created.setup_url && created.setup_expires_at) {
        setLink({
          title: 'Account setup link',
          name: created.user.full_name,
          url: created.setup_url,
          expiresAt: created.setup_expires_at,
        });
      }
    }
    setFormOpen(false);
    setEditing(null);
    invalidate();
  };

  const columns: Column<UserOut>[] = [
    {
      key: 'name',
      header: 'Name',
      render: (u) => (
        <div className="min-w-[10rem]">
          <p className="font-medium text-gray-900">
            {u.full_name}
            {u.id === me?.id && <span className="ml-1.5 text-xs font-normal text-gray-500">(you)</span>}
          </p>
          <p className="text-xs text-gray-500">@{u.username}</p>
        </div>
      ),
    },
    { key: 'role', header: 'Role', render: (u) => <Badge tone="blue">{u.role.display_name}</Badge> },
    {
      key: 'contact',
      header: 'Contact',
      hideOnMobile: true,
      render: (u) => (
        <div className="text-xs">
          <p className="text-gray-700">{u.email}</p>
          {u.phone && <p className="text-gray-500">{u.phone}</p>}
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (u) => (
        <div className="flex flex-wrap gap-1">
          {u.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="gray">Deactivated</Badge>}
          {u.is_locked && <Badge tone="red">Locked</Badge>}
          {u.must_change_password && u.is_active && <Badge tone="amber">Password pending</Badge>}
        </div>
      ),
    },
    {
      key: 'last',
      header: 'Last sign-in',
      hideOnMobile: true,
      render: (u) => <span className="whitespace-nowrap text-xs text-gray-500">{formatDateTime(u.last_login_at)}</span>,
    },
    {
      key: 'actions',
      header: <span className="sr-only">Actions</span>,
      className: 'w-12 text-right',
      render: (u) =>
        canManage ? (
          <ActionMenu
            label={`Actions for ${u.full_name}`}
            items={[
              { label: 'Edit details', icon: <Pencil className="h-4 w-4" />, onClick: () => { setEditing(u); setFormOpen(true); } },
              { label: 'Create reset link', icon: <KeyRound className="h-4 w-4" />, onClick: () => resetLink(u), hidden: !u.is_active },
              { label: 'Unlock account', icon: <Unlock className="h-4 w-4" />, onClick: () => unlock(u), hidden: !u.is_locked },
              { label: 'Sign out everywhere', icon: <LogOut className="h-4 w-4" />, onClick: () => setConfirm({ kind: 'signout', user: u }), hidden: u.id === me?.id },
              { label: 'Reactivate', icon: <UserCheck className="h-4 w-4" />, onClick: () => setConfirm({ kind: 'activate', user: u }), hidden: u.is_active },
              { label: 'Deactivate', icon: <UserX className="h-4 w-4" />, danger: true, onClick: () => setConfirm({ kind: 'deactivate', user: u }), hidden: !u.is_active || u.id === me?.id },
            ]}
          />
        ) : null,
    },
  ];

  const data = usersQuery.data;
  const confirmText = confirm && {
    deactivate: {
      title: 'Deactivate this account?',
      body: `${confirm.user.full_name} will be signed out immediately and will not be able to sign in. Their history is kept. You can reactivate the account later.`,
      label: 'Deactivate',
      tone: 'danger' as const,
    },
    activate: {
      title: 'Reactivate this account?',
      body: `${confirm.user.full_name} will be able to sign in again with their existing password.`,
      label: 'Reactivate',
      tone: 'primary' as const,
    },
    signout: {
      title: 'Sign out on every device?',
      body: `${confirm.user.full_name} will be signed out on all phones and computers and will need to sign in again.`,
      label: 'Sign out everywhere',
      tone: 'danger' as const,
    },
  }[confirm.kind];

  return (
    <>
      <PageHeader
        title="Users"
        description="Staff accounts and the role each person has."
        actions={
          canManage && (
            <Button icon={<UserPlus className="h-4 w-4" />} onClick={() => { setEditing(null); setFormOpen(true); }}>
              Add staff member
            </Button>
          )
        }
      />

      <Card bodyClassName="p-0">
        <div className="flex flex-col gap-3 border-b border-gray-100 p-4 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" aria-hidden />
            <input
              type="search"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              placeholder="Search name, username or email"
              aria-label="Search users"
              className="h-10 w-full rounded-lg border border-gray-300 pl-9 pr-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30"
            />
          </div>
          <div className="grid grid-cols-2 gap-3 sm:flex">
            <select
              value={role}
              onChange={(e) => { setRole(e.target.value); setPage(1); }}
              aria-label="Filter by role"
              className="h-10 rounded-lg border border-gray-300 px-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30"
            >
              <option value="">All roles</option>
              {rolesQuery.data?.map((r) => (
                <option key={r.name} value={r.name}>{r.display_name}</option>
              ))}
            </select>
            <select
              value={status}
              onChange={(e) => { setStatus(e.target.value as typeof status); setPage(1); }}
              aria-label="Filter by status"
              className="h-10 rounded-lg border border-gray-300 px-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30"
            >
              <option value="">Any status</option>
              <option value="active">Active</option>
              <option value="inactive">Deactivated</option>
            </select>
          </div>
        </div>

        {usersQuery.isError ? (
          <div className="p-4"><Alert tone="error">{errorMessage(usersQuery.error)}</Alert></div>
        ) : (
          <DataTable
            caption="Users"
            columns={columns}
            rows={data?.items ?? []}
            rowKey={(u) => u.id}
            loading={usersQuery.isFetching}
            emptyTitle="No users found"
            emptyDescription={search || role || status ? 'Try a different search or filter.' : undefined}
          />
        )}
        {data && data.total > 0 && (
          <Pagination page={data.page} pages={data.pages} total={data.total} pageSize={data.page_size} onPageChange={setPage} />
        )}
      </Card>

      <UserFormModal
        open={formOpen}
        roles={rolesQuery.data ?? []}
        user={editing}
        currentUserId={me?.id ?? 0}
        onClose={() => { setFormOpen(false); setEditing(null); }}
        onSubmit={submitForm}
      />
      <LinkModal link={link} onClose={() => setLink(null)} />
      <ConfirmDialog
        open={Boolean(confirm)}
        title={confirmText?.title ?? ''}
        message={confirmText?.body}
        confirmLabel={confirmText?.label}
        tone={confirmText?.tone}
        loading={actionMutation.isPending}
        onConfirm={() => confirm && actionMutation.mutate(confirm)}
        onCancel={() => setConfirm(null)}
      />
    </>
  );
}

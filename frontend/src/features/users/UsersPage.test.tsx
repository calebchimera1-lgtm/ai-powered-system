import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '@/api/client';
import type { RoleName, UserOut } from '@/api/types';
import { usersApi } from '@/api/users';
import { makeUser, renderWithProviders } from '@/test/utils';

import { UsersPage } from './UsersPage';

vi.mock('@/api/users', () => ({
  usersApi: {
    list: vi.fn(),
    roles: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    issueReset: vi.fn(),
    unlock: vi.fn(),
    revokeSessions: vi.fn(),
  },
}));

const sample: UserOut = {
  id: 2,
  full_name: 'David Kiprop',
  username: 'dkiprop',
  email: 'david@test.local',
  phone: '+254700000000',
  role: { id: 4, name: 'cashier', display_name: 'Cashier' },
  is_active: true,
  must_change_password: false,
  is_locked: true,
  last_login_at: null,
  created_at: '2026-11-01T08:00:00Z',
};

function setup(role: RoleName) {
  vi.spyOn(client, 'refreshAccessToken').mockResolvedValue({
    access_token: 't',
    token_type: 'bearer',
    expires_in: 900,
    user: makeUser(role),
  });
  vi.mocked(usersApi.list).mockResolvedValue({ items: [sample], total: 1, page: 1, page_size: 20, pages: 1 });
  vi.mocked(usersApi.roles).mockResolvedValue([
    { id: 4, name: 'cashier', display_name: 'Cashier', description: 'Point of sale', permissions: [], user_count: 1 },
  ]);
  return renderWithProviders(<UsersPage />);
}

describe('UsersPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it('lists users with status badges', async () => {
    setup('super_admin');
    const row = (await screen.findByText('David Kiprop')).closest('tr')!;
    expect(within(row).getByText('Locked')).toBeInTheDocument();
    expect(within(row).getByText('Cashier')).toBeInTheDocument();
  });

  it('store managers can view but not manage', async () => {
    setup('store_manager');
    await screen.findByText('David Kiprop');
    expect(screen.queryByRole('button', { name: /add staff member/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /actions for/i })).not.toBeInTheDocument();
  });

  it('asks for confirmation before deactivating', async () => {
    vi.mocked(usersApi.update).mockResolvedValue({ ...sample, is_active: false });
    setup('super_admin');
    await userEvent.click(await screen.findByRole('button', { name: 'Actions for David Kiprop' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Deactivate' }));
    const dialog = screen.getByRole('dialog', { name: 'Deactivate this account?' });
    expect(usersApi.update).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Deactivate' }));
    expect(usersApi.update).toHaveBeenCalledWith(2, { is_active: false });
  });

  it('creates a user and shows the one-time setup link', async () => {
    vi.mocked(usersApi.create).mockResolvedValue({
      user: { ...sample, id: 3, full_name: 'Grace Njeri', username: 'gnjeri' },
      setup_url: 'http://localhost:8080/reset-password?token=abc',
      setup_expires_at: '2026-11-05T12:00:00Z',
    });
    setup('super_admin');
    await userEvent.click(await screen.findByRole('button', { name: /add staff member/i }));
    const dialog = screen.getByRole('dialog', { name: 'Add staff member' });
    await userEvent.type(within(dialog).getByLabelText(/full name/i), 'Grace Njeri');
    await userEvent.type(within(dialog).getByLabelText(/^username/i), 'gnjeri');
    await userEvent.type(within(dialog).getByLabelText(/^email/i), 'grace@example.com');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create account' }));
    expect(usersApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ username: 'gnjeri', role: 'cashier', password: null }),
    );
    expect(await screen.findByDisplayValue('http://localhost:8080/reset-password?token=abc')).toBeInTheDocument();
  });
});

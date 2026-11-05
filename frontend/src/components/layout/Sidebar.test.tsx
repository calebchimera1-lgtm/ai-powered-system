import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { RoleName } from '@/api/types';
import * as client from '@/api/client';
import { makeUser, renderWithProviders } from '@/test/utils';

import { Sidebar } from './Sidebar';

function setup(role: RoleName) {
  vi.spyOn(client, 'refreshAccessToken').mockResolvedValue({
    access_token: 't',
    token_type: 'bearer',
    expires_in: 900,
    user: makeUser(role),
  });
  return renderWithProviders(<Sidebar mobileOpen={false} onClose={() => {}} />);
}

describe('Sidebar navigation is filtered by permission', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('super admin sees users and audit log', async () => {
    setup('super_admin');
    expect(await screen.findByRole('link', { name: 'Users' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Audit log' })).toBeInTheDocument();
  });

  it('store manager sees users but not the audit log', async () => {
    setup('store_manager');
    expect(await screen.findByRole('link', { name: 'Users' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Audit log' })).not.toBeInTheDocument();
  });

  it('cashier sees neither', async () => {
    setup('cashier');
    expect(await screen.findByRole('link', { name: 'My account' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Users' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Audit log' })).not.toBeInTheDocument();
  });
});

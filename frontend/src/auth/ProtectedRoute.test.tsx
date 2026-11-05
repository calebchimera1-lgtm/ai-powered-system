import { screen } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '@/api/client';
import { makeUser, renderWithProviders } from '@/test/utils';

import { RequireAuth, RequirePermission } from './ProtectedRoute';

function tree() {
  return (
    <Routes>
      <Route path="/login" element={<p>Login screen</p>} />
      <Route element={<RequireAuth />}>
        <Route path="/change-password" element={<p>Change password screen</p>} />
        <Route path="/" element={<p>Home screen</p>} />
        <Route
          path="/users"
          element={
            <RequirePermission anyOf={['users:read']}>
              <p>Users screen</p>
            </RequirePermission>
          }
        />
      </Route>
    </Routes>
  );
}

function session(user: ReturnType<typeof makeUser> | null) {
  const spy = vi.spyOn(client, 'refreshAccessToken');
  if (user) spy.mockResolvedValue({ access_token: 't', token_type: 'bearer', expires_in: 900, user });
  else spy.mockRejectedValue(new Error('no session'));
}

describe('route guards', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('redirects anonymous visitors to sign in', async () => {
    session(null);
    renderWithProviders(tree(), { route: '/' });
    expect(await screen.findByText('Login screen')).toBeInTheDocument();
  });

  it('restores a session from the refresh cookie', async () => {
    session(makeUser('cashier'));
    renderWithProviders(tree(), { route: '/' });
    expect(await screen.findByText('Home screen')).toBeInTheDocument();
  });

  it('forces a temporary password to be changed first', async () => {
    session(makeUser('super_admin', { must_change_password: true }));
    renderWithProviders(tree(), { route: '/users' });
    expect(await screen.findByText('Change password screen')).toBeInTheDocument();
  });

  it('blocks pages the role cannot use', async () => {
    session(makeUser('cashier'));
    renderWithProviders(tree(), { route: '/users' });
    expect(await screen.findByText(/don't have access/i)).toBeInTheDocument();
    expect(screen.queryByText('Users screen')).not.toBeInTheDocument();
  });
});

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

describe('sign-out on a shared device', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('the next person to sign in starts at Home, not on the previous page', async () => {
    const { userEvent } = await import('@testing-library/user-event').then((m) => ({ userEvent: m.default }));
    const { authApi } = await import('@/api/auth');
    const { useAuth } = await import('./AuthProvider');
    const { LoginPage } = await import('@/features/auth/LoginPage');
    vi.spyOn(authApi, 'logout').mockResolvedValue({ message: 'ok' });
    vi.spyOn(authApi, 'login').mockResolvedValue({ access_token: 't2', token_type: 'bearer', expires_in: 900, user: makeUser('cashier', { id: 2 }) });
    session(makeUser('super_admin'));

    function SignOutButton() {
      const { logout } = useAuth();
      return <button onClick={() => logout()}>Sign out</button>;
    }
    renderWithProviders(
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<p>Home screen</p>} />
          <Route path="/users" element={<><p>Users screen</p><SignOutButton /></>} />
        </Route>
      </Routes>,
      { route: '/users' },
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }));
    await userEvent.type(await screen.findByLabelText(/username or email/i), 'till');
    await userEvent.type(screen.getByLabelText(/^password/i), 'Secret-123');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(await screen.findByText('Home screen')).toBeInTheDocument();
    expect(screen.queryByText('Users screen')).not.toBeInTheDocument();
  });
});

import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { authApi } from '@/api/auth';
import * as client from '@/api/client';
import { makeUser, renderWithProviders } from '@/test/utils';

import { LoginPage } from './LoginPage';

vi.mock('@/api/auth', () => ({ authApi: { login: vi.fn(), logout: vi.fn(), me: vi.fn() } }));

function renderLogin() {
  return renderWithProviders(
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<p>Home screen</p>} />
      <Route path="/change-password" element={<p>Change password screen</p>} />
    </Routes>,
    { route: '/login' },
  );
}

describe('LoginPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(client, 'refreshAccessToken').mockRejectedValue(new Error('no session'));
  });

  it('validates required fields before calling the API', async () => {
    renderLogin();
    await userEvent.click(await screen.findByRole('button', { name: /sign in/i }));
    expect(await screen.findByText('Enter your username or email')).toBeInTheDocument();
    expect(screen.getByText('Enter your password')).toBeInTheDocument();
    expect(authApi.login).not.toHaveBeenCalled();
  });

  it('signs in and goes to the home screen', async () => {
    vi.mocked(authApi.login).mockResolvedValue({
      access_token: 'tok',
      token_type: 'bearer',
      expires_in: 900,
      user: makeUser('cashier'),
    });
    renderLogin();
    await userEvent.type(await screen.findByLabelText(/username or email/i), 'amina');
    await userEvent.type(screen.getByLabelText(/^password/i), 'Secret-123');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(await screen.findByText('Home screen')).toBeInTheDocument();
    expect(authApi.login).toHaveBeenCalledWith('amina', 'Secret-123');
    expect(client.getAccessToken()).toBe('tok');
  });

  it('sends users with a temporary password to the change-password screen', async () => {
    vi.mocked(authApi.login).mockResolvedValue({
      access_token: 'tok',
      token_type: 'bearer',
      expires_in: 900,
      user: makeUser('cashier', { must_change_password: true }),
    });
    renderLogin();
    await userEvent.type(await screen.findByLabelText(/username or email/i), 'amina');
    await userEvent.type(screen.getByLabelText(/^password/i), 'Temp-Pass-1');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(await screen.findByText('Change password screen')).toBeInTheDocument();
  });

  it('shows the server error message on failure', async () => {
    const { AxiosError, AxiosHeaders } = await import('axios');
    const config = { headers: new AxiosHeaders() };
    vi.mocked(authApi.login).mockRejectedValue(
      new AxiosError('401', 'ERR', config, null, {
        status: 401,
        statusText: '',
        headers: {},
        config,
        data: { error: { code: 'UNAUTHENTICATED', message: 'Invalid username or password' } },
      }),
    );
    renderLogin();
    await userEvent.type(await screen.findByLabelText(/username or email/i), 'amina');
    await userEvent.type(screen.getByLabelText(/^password/i), 'wrong-one-1');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Invalid username or password'));
  });
});

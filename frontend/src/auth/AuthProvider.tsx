import { useQueryClient } from '@tanstack/react-query';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { authApi } from '@/api/auth';
import { refreshAccessToken, setAccessToken, setSessionHandlers } from '@/api/client';
import type { CurrentUser } from '@/api/types';

import type { PermissionCode } from './permissions';

type Status = 'loading' | 'authenticated' | 'anonymous';

interface AuthContextValue {
  status: Status;
  user: CurrentUser | null;
  /** Set when the session ended unexpectedly (expired or revoked elsewhere). */
  sessionExpired: boolean;
  login: (username: string, password: string) => Promise<CurrentUser>;
  logout: () => Promise<void>;
  reloadUser: () => Promise<void>;
  can: (permission: PermissionCode) => boolean;
  canAny: (...permissions: PermissionCode[]) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Status>('loading');
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);

  const clear = useCallback(() => {
    setAccessToken(null);
    setUser(null);
    setStatus('anonymous');
    queryClient.clear();
  }, [queryClient]);

  // Wire the API client's refresh events into React state.
  useEffect(() => {
    setSessionHandlers({
      expired: () => {
        setSessionExpired(true);
        clear();
      },
      refreshed: (data) => setUser(data.user),
    });
  }, [clear]);

  // On first load, try to restore the session from the HttpOnly refresh cookie.
  useEffect(() => {
    let cancelled = false;
    refreshAccessToken()
      .then((data) => {
        if (cancelled) return;
        setUser(data.user);
        setStatus('authenticated');
      })
      .catch(() => {
        if (!cancelled) setStatus('anonymous');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const data = await authApi.login(username, password);
    setAccessToken(data.access_token);
    setUser(data.user);
    setSessionExpired(false);
    setStatus('authenticated');
    return data.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // Already signed out server-side; clear locally regardless.
    }
    setSessionExpired(false);
    clear();
  }, [clear]);

  const reloadUser = useCallback(async () => {
    setUser(await authApi.me());
  }, []);

  const value = useMemo<AuthContextValue>(() => {
    const granted = new Set(user?.permissions ?? []);
    return {
      status,
      user,
      sessionExpired,
      login,
      logout,
      reloadUser,
      can: (p) => granted.has(p),
      canAny: (...ps) => ps.some((p) => granted.has(p)),
    };
  }, [status, user, sessionExpired, login, logout, reloadUser]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}

import axios, { AxiosError, type AxiosRequestConfig } from 'axios';

import type { ApiErrorBody, TokenResponse } from './types';

/**
 * Axios instance for the API.
 *
 * - The access token lives only in memory (never localStorage), so XSS cannot read a
 *   long-lived credential.
 * - The refresh token is an HttpOnly cookie the browser sends to /api/v1/auth only.
 * - On a 401 the client refreshes once (shared between concurrent requests) and retries.
 */
export const api = axios.create({
  baseURL: '/api/v1',
  withCredentials: true,
  headers: { 'X-Requested-With': 'XMLHttpRequest' },
  timeout: 30_000,
});

let accessToken: string | null = null;
let refreshPromise: Promise<TokenResponse> | null = null;
let onSessionExpired: (() => void) | null = null;
let onTokenRefreshed: ((data: TokenResponse) => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function setSessionHandlers(handlers: {
  expired: () => void;
  refreshed: (data: TokenResponse) => void;
}): void {
  onSessionExpired = handlers.expired;
  onTokenRefreshed = handlers.refreshed;
}

/** Exchange the refresh cookie for a new access token. Concurrent callers share one request. */
export function refreshAccessToken(): Promise<TokenResponse> {
  if (!refreshPromise) {
    refreshPromise = api
      .post<TokenResponse>('/auth/refresh', null, { skipAuthRefresh: true } as AxiosRequestConfig)
      .then((res) => {
        setAccessToken(res.data.access_token);
        onTokenRefreshed?.(res.data);
        return res.data;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

declare module 'axios' {
  interface AxiosRequestConfig {
    skipAuthRefresh?: boolean;
    _retried?: boolean;
  }
}

api.interceptors.request.use((config) => {
  if (accessToken && !config.headers.Authorization) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiErrorBody>) => {
    const original = error.config;
    const status = error.response?.status;
    const url = original?.url ?? '';
    const isAuthCall = url.includes('/auth/login') || url.includes('/auth/refresh');

    if (status === 401 && original && !original._retried && !original.skipAuthRefresh && !isAuthCall) {
      original._retried = true;
      try {
        const data = await refreshAccessToken();
        original.headers.Authorization = `Bearer ${data.access_token}`;
        return api.request(original);
      } catch {
        setAccessToken(null);
        onSessionExpired?.();
      }
    }
    return Promise.reject(error);
  },
);

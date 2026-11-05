import { api } from './client';
import type { CurrentUser, Message, SessionOut, TokenResponse } from './types';

export const authApi = {
  login: (username: string, password: string) =>
    api.post<TokenResponse>('/auth/login', { username, password }).then((r) => r.data),
  logout: () => api.post<Message>('/auth/logout').then((r) => r.data),
  me: () => api.get<CurrentUser>('/auth/me').then((r) => r.data),
  changePassword: (current_password: string, new_password: string) =>
    api.post<Message>('/auth/change-password', { current_password, new_password }).then((r) => r.data),
  resetPassword: (token: string, new_password: string) =>
    api.post<Message>('/auth/reset-password', { token, new_password }).then((r) => r.data),
  sessions: () => api.get<SessionOut[]>('/auth/sessions').then((r) => r.data),
  revokeSession: (id: number) => api.delete<Message>(`/auth/sessions/${id}`).then((r) => r.data),
};

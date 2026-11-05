import { api } from './client';
import type {
  Message,
  Page,
  PasswordResetIssued,
  RoleName,
  RoleOut,
  UserCreated,
  UserOut,
} from './types';

export interface UserListParams {
  page?: number;
  page_size?: number;
  search?: string;
  role?: string;
  is_active?: boolean;
}

export interface UserCreateInput {
  full_name: string;
  username: string;
  email: string;
  phone?: string | null;
  role: RoleName;
  password?: string | null;
}

export interface UserUpdateInput {
  full_name?: string;
  email?: string;
  phone?: string | null;
  role?: RoleName;
  is_active?: boolean;
}

/** Drop empty filter values so they are not sent as `?search=`. */
function clean<T extends object>(params: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''),
  ) as Partial<T>;
}

export const usersApi = {
  list: (params: UserListParams) =>
    api.get<Page<UserOut>>('/users', { params: clean(params) }).then((r) => r.data),
  create: (body: UserCreateInput) => api.post<UserCreated>('/users', body).then((r) => r.data),
  update: (id: number, body: UserUpdateInput) =>
    api.patch<UserOut>(`/users/${id}`, body).then((r) => r.data),
  issueReset: (id: number) =>
    api.post<PasswordResetIssued>(`/users/${id}/reset-password`).then((r) => r.data),
  unlock: (id: number) => api.post<UserOut>(`/users/${id}/unlock`).then((r) => r.data),
  revokeSessions: (id: number) =>
    api.post<Message>(`/users/${id}/revoke-sessions`).then((r) => r.data),
  roles: () => api.get<RoleOut[]>('/roles').then((r) => r.data),
};

import { api } from './client';
import type { AuditLogOut, Page } from './types';

export interface AuditParams {
  page?: number;
  page_size?: number;
  action?: string;
  user_id?: number;
  entity_type?: string;
  date_from?: string;
  date_to?: string;
}

export const auditApi = {
  list: (params: AuditParams) => {
    const cleaned = Object.fromEntries(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== ''),
    );
    return api.get<Page<AuditLogOut>>('/audit-logs', { params: cleaned }).then((r) => r.data);
  },
};

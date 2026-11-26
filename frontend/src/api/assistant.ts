import { api } from './client';
import type { Page, UserBrief } from './types';

export interface ToolCall {
  tool: string;
  input: unknown;
  ok: boolean;
  summary: string;
}

export interface AssistantMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  attachment_name: string | null;
  attachment_mime: string | null;
  has_attachment: boolean;
  tool_log: ToolCall[] | null;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  error: string | null;
  created_at: string;
}

export interface Proposal {
  id: number;
  message_id: number | null;
  kind: 'EXPENSE' | 'INVOICE';
  payload: Record<string, string | number | boolean | null>;
  status: 'PENDING' | 'CONFIRMED' | 'CANCELLED';
  result_id: number | null;
  decided_at: string | null;
  created_at: string;
}

export interface Conversation {
  id: number;
  title: string;
  user: UserBrief;
  created_at: string;
  updated_at: string;
  messages: AssistantMessage[];
  proposals: Proposal[];
}

export interface ConversationSummary {
  id: number;
  title: string;
  user: UserBrief;
  created_at: string;
  updated_at: string;
  messages: number;
}

export interface AssistantStatus {
  enabled: boolean;
  model: string | null;
  ai_invoice_reading: boolean;
  tools: string[];
  can_see_all: boolean;
}

export const assistantApi = {
  status: () => api.get<AssistantStatus>('/assistant/status').then((r) => r.data),
  conversations: (q: { page?: number; everyone?: boolean }) =>
    api
      .get<Page<ConversationSummary>>('/assistant/conversations', { params: { page_size: 30, ...q } })
      .then((r) => r.data),
  conversation: (id: number) =>
    api.get<Conversation>(`/assistant/conversations/${id}`).then((r) => r.data),
  /** Claude may look up several records before answering: allow it time. */
  ask: (body: { text: string; conversationId?: number | null; file?: File | null }) => {
    const form = new FormData();
    form.append('text', body.text);
    if (body.conversationId) form.append('conversation_id', String(body.conversationId));
    if (body.file) form.append('file', body.file);
    return api.post<Conversation>('/assistant/messages', form, { timeout: 300_000 }).then((r) => r.data);
  },
  attachment: (messageId: number) =>
    api
      .get<Blob>(`/assistant/messages/${messageId}/attachment`, { responseType: 'blob' })
      .then((r) => r.data),
  confirm: (id: number) => api.post<Proposal>(`/assistant/proposals/${id}/confirm`).then((r) => r.data),
  cancel: (id: number) => api.post<Proposal>(`/assistant/proposals/${id}/cancel`).then((r) => r.data),
};

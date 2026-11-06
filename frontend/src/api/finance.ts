import { api } from './client';
import type { AnalyticsOverview, Expense, ExpenseCategory, Message, Page } from './types';

function clean<T extends object>(params: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''),
  ) as Partial<T>;
}

export interface ExpenseInput {
  category_id: number;
  expense_date: string;
  amount: string;
  description: string;
  payment_method: 'CASH' | 'MPESA' | 'CARD' | 'BANK';
  reference?: string | null;
}

export const financeApi = {
  overview: (q: { date_from?: string; date_to?: string }) =>
    api.get<AnalyticsOverview>('/analytics/overview', { params: clean(q) }).then((r) => r.data),
  categories: () => api.get<ExpenseCategory[]>('/expense-categories').then((r) => r.data),
  expenses: (q: { page?: number; page_size?: number; date_from?: string; date_to?: string; category_id?: number }) =>
    api
      .get<Page<Expense> & { total_amount: string }>('/expenses', { params: clean(q) })
      .then((r) => r.data),
  createExpense: (body: ExpenseInput) => api.post<Expense>('/expenses', body).then((r) => r.data),
  updateExpense: (id: number, body: ExpenseInput) =>
    api.put<Expense>(`/expenses/${id}`, body).then((r) => r.data),
  deleteExpense: (id: number) => api.delete<Message>(`/expenses/${id}`).then((r) => r.data),
};

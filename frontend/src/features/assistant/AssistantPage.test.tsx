import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { assistantApi, type Conversation } from '@/api/assistant';
import * as client from '@/api/client';
import { makeUser, renderWithProviders } from '@/test/utils';

import { AssistantPage } from './AssistantPage';
import { MessageText } from './MessageText';

vi.mock('@/api/assistant', () => ({
  assistantApi: {
    status: vi.fn(),
    conversations: vi.fn(),
    conversation: vi.fn(),
    ask: vi.fn(),
    attachment: vi.fn(),
    confirm: vi.fn(),
    cancel: vi.fn(),
  },
}));

const user = { id: 1, username: 'amina', full_name: 'Amina Wanjiru' };

function conversation(): Conversation {
  return {
    id: 7,
    title: 'Record this receipt',
    user,
    created_at: '2026-11-26T08:00:00Z',
    updated_at: '2026-11-26T08:00:05Z',
    messages: [
      {
        id: 1, role: 'user', content: 'Record this receipt', attachment_name: 'kplc.pdf',
        attachment_mime: 'application/pdf', has_attachment: true, tool_log: null, model: null,
        input_tokens: null, output_tokens: null, error: null, created_at: '2026-11-26T08:00:00Z',
      },
      {
        id: 2, role: 'assistant', content: 'This is a **Kenya Power** receipt.\n\n- Total: KES 4,520.00',
        attachment_name: null, attachment_mime: null, has_attachment: false,
        tool_log: [{ tool: 'expense_categories', input: {}, ok: true, summary: '[]' }],
        model: 'claude-opus-5-5', input_tokens: 900, output_tokens: 80, error: null,
        created_at: '2026-11-26T08:00:05Z',
      },
    ],
    proposals: [
      {
        id: 3, message_id: 2, kind: 'EXPENSE', status: 'PENDING', result_id: null, decided_at: null,
        created_at: '2026-11-26T08:00:05Z',
        payload: { amount: '4520.00', category_name: 'Electricity', expense_date: '2026-11-20', payment_method: 'MPESA', description: 'KPLC token', reference: 'QK7Y2LM9PA' },
      },
    ],
  };
}

function renderPage(route = '/assistant') {
  vi.spyOn(client, 'refreshAccessToken').mockResolvedValue({ access_token: 't', token_type: 'bearer', expires_in: 900, user: makeUser('store_manager') });
  return renderWithProviders(<Routes><Route path="/assistant" element={<AssistantPage />} /></Routes>, { route });
}

describe('AssistantPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(assistantApi.conversations).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 30, pages: 1 });
  });

  it('explains how to switch it on when the server has no API key', async () => {
    vi.mocked(assistantApi.status).mockResolvedValue({ enabled: false, model: null, ai_invoice_reading: false, tools: [], can_see_all: false });
    renderPage();
    expect(await screen.findByText(/not switched on for this shop yet/i)).toBeInTheDocument();
    expect(screen.getByLabelText('Your question')).toBeDisabled();
  });

  it('sends a suggested question and shows the answer, records checked and the proposal', async () => {
    vi.mocked(assistantApi.status).mockResolvedValue({ enabled: true, model: 'claude-opus-5-5', ai_invoice_reading: true, tools: ['financial_summary', 'propose_expense', 'expense_categories'], can_see_all: false });
    vi.mocked(assistantApi.ask).mockResolvedValue(conversation());
    vi.mocked(assistantApi.conversation).mockResolvedValue(conversation());
    vi.mocked(assistantApi.confirm).mockResolvedValue({ ...conversation().proposals[0]!, status: 'CONFIRMED', result_id: 11 });
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: /How much profit did we make this month/ }));
    expect(assistantApi.ask).toHaveBeenCalledWith(expect.objectContaining({ text: expect.stringMatching(/profit/), conversationId: undefined }));
    expect(await screen.findByText('Kenya Power')).toHaveProperty('tagName', 'STRONG');
    expect(screen.getByText(/Records checked \(1\)/)).toBeInTheDocument();
    expect(screen.getByText('Record this expense?')).toBeInTheDocument();
    expect(screen.getByText('KPLC token')).toBeInTheDocument();
    expect(screen.getByText('kplc.pdf')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(assistantApi.confirm).toHaveBeenCalled());
    expect(vi.mocked(assistantApi.confirm).mock.calls[0]?.[0]).toBe(3);
  });

  it('attaches a receipt photo and sends it with the question', async () => {
    vi.mocked(assistantApi.status).mockResolvedValue({ enabled: true, model: 'm', ai_invoice_reading: true, tools: [], can_see_all: false });
    vi.mocked(assistantApi.ask).mockResolvedValue(conversation());
    vi.mocked(assistantApi.conversation).mockResolvedValue(conversation());
    renderPage();
    const file = new File(['x'], 'receipt.png', { type: 'image/png' });
    await userEvent.upload(await screen.findByLabelText('Receipt or invoice file'), file);
    expect(screen.getByText('receipt.png')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Your question'), 'Record this{Enter}');
    expect(assistantApi.ask).toHaveBeenCalledWith({ text: 'Record this', conversationId: undefined, file });
  });
});

describe('MessageText', () => {
  it('never turns model output into HTML', () => {
    const { container } = render(<MessageText text={'<img src=x onerror=alert(1)> **ok**'} />);
    expect(container.querySelector('img')).toBeNull();
    expect(container.textContent).toContain('<img src=x onerror=alert(1)>');
  });

  it('renders a pipe table', () => {
    render(<MessageText text={'| Day | Sales |\n|---|---|\n| Mon | KES 100 |'} />);
    expect(screen.getByRole('columnheader', { name: 'Sales' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'KES 100' })).toBeInTheDocument();
  });
});

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Bot,
  Camera,
  CheckCircle2,
  FileText,
  History,
  Loader2,
  MessageSquarePlus,
  Paperclip,
  Search,
  Send,
  X,
  XCircle,
} from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import {
  assistantApi,
  type AssistantMessage,
  type Conversation,
  type Proposal,
} from '@/api/assistant';
import { useAuth } from '@/auth/AuthProvider';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { PageHeader } from '@/components/ui/Card';
import { useToast } from '@/components/ui/Toast';
import { errorMessage } from '@/lib/errors';
import { formatDateTime, formatKES } from '@/lib/format';

import { checkFile } from '../invoices/InvoicesPage';
import { MessageText } from './MessageText';

const TOOL_LABEL: Record<string, string> = {
  financial_summary: 'Income statement',
  daily_sales: 'Daily sales',
  product_performance: 'Best-selling products',
  category_performance: 'Sales by category',
  payment_methods: 'Payment methods',
  list_expenses: 'Expenses',
  expense_categories: 'Expense categories',
  propose_expense: 'Prepared an expense',
  propose_supplier_invoice: 'Prepared an invoice upload',
  search_products: 'Product search',
  stock_alerts: 'Stock alerts',
  supplier_invoices: 'Supplier invoices',
  audit_trail: 'Audit log',
};

/** Suggestions shown on an empty chat, filtered by what this user's assistant can do. */
const SUGGESTIONS: { text: string; needs: string }[] = [
  { text: 'How much profit did we make this month, and what were the biggest expenses?', needs: 'financial_summary' },
  { text: 'Mauzo ya leo ni kiasi gani? (What are today’s sales?)', needs: 'daily_sales' },
  { text: 'Which products are low on stock or expiring soon?', needs: 'stock_alerts' },
  { text: 'Which supplier invoices are waiting for review?', needs: 'supplier_invoices' },
  { text: 'Record KES 3,500 for transport today, paid by M-Pesa', needs: 'propose_expense' },
  { text: 'What is the price of sugar and how much is in stock?', needs: 'search_products' },
  { text: 'Who recorded expenses this week?', needs: 'audit_trail' },
];

export function AssistantPage() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const convId = Number(params.get('c')) || null;
  const [everyone, setEveryone] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  const status = useQuery({ queryKey: ['assistant', 'status'], queryFn: assistantApi.status });
  const list = useQuery({
    queryKey: ['assistant', 'conversations', everyone],
    queryFn: () => assistantApi.conversations({ everyone }),
  });
  const conv = useQuery({
    queryKey: ['assistant', 'conversation', convId],
    queryFn: () => assistantApi.conversation(convId as number),
    enabled: convId !== null,
  });

  const open = (id: number | null) => {
    setShowHistory(false);
    setParams(id ? { c: String(id) } : {});
  };
  const onAnswered = (c: Conversation) => {
    qc.setQueryData(['assistant', 'conversation', c.id], c);
    void qc.invalidateQueries({ queryKey: ['assistant', 'conversations'] });
    if (c.id !== convId) setParams({ c: String(c.id) });
  };

  const enabled = status.data?.enabled ?? false;
  // Auditors can read other people's conversations, but only the owner can continue one.
  const othersConversation = Boolean(conv.data && user && conv.data.user.id !== user.id);

  return (
    <>
      <PageHeader
        title="AI accounting assistant"
        description="Ask about sales, profit, expenses and stock, or attach a receipt or invoice to scan it. Every question, answer and action is logged."
        actions={
          <>
            <Button variant="secondary" className="lg:hidden" icon={<History className="h-4 w-4" />} onClick={() => setShowHistory((v) => !v)}>
              History
            </Button>
            <Button icon={<MessageSquarePlus className="h-4 w-4" />} onClick={() => open(null)}>New chat</Button>
          </>
        }
      />
      {status.data && !enabled && (
        <div className="mb-4">
          <Alert tone="warning">
            The AI assistant is not switched on for this shop yet. An administrator adds a Claude
            API key (ANTHROPIC_API_KEY) to the server’s <code>.env</code> file and restarts the app;
            see the installation guide, section “AI assistant”. Until then, invoices are still read
            with the built-in OCR under Purchasing → Scan invoices.
          </Alert>
        </div>
      )}
      <div className="grid min-w-0 gap-4 lg:grid-cols-[17rem_minmax(0,1fr)]">
        <aside className={clsx('min-w-0 rounded-xl border border-gray-200 bg-white shadow-card', showHistory ? 'block' : 'hidden lg:block')}>
          <div className="flex items-center justify-between gap-2 border-b border-gray-100 px-4 py-3">
            <h2 className="text-sm font-semibold text-gray-900">{everyone ? 'All staff (log)' : 'Your conversations'}</h2>
            {status.data?.can_see_all && (
              <button type="button" className="text-xs font-medium text-brand-700 hover:underline" onClick={() => setEveryone((v) => !v)}>
                {everyone ? 'Show mine' : 'All staff'}
              </button>
            )}
          </div>
          <ul className="max-h-[60vh] overflow-y-auto py-1 text-sm" aria-label="Conversations">
            {list.data?.items.length === 0 && <li className="px-4 py-3 text-gray-500">No conversations yet.</li>}
            {list.data?.items.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => open(c.id)}
                  className={clsx('block w-full px-4 py-2 text-left hover:bg-gray-50', c.id === convId && 'bg-brand-50')}
                  aria-current={c.id === convId ? 'true' : undefined}
                >
                  <span className="block truncate font-medium text-gray-800">{c.title}</span>
                  <span className="block truncate text-xs text-gray-500">
                    {formatDateTime(c.updated_at)}{everyone ? ` · ${c.user.full_name}` : ''} · {c.messages} messages
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </aside>
        <Chat
          key={convId ?? 'new'}
          conversation={convId ? conv.data ?? null : null}
          loading={convId !== null && conv.isLoading}
          loadError={conv.error ? errorMessage(conv.error) : null}
          enabled={enabled}
          tools={status.data?.tools ?? []}
          readOnly={othersConversation}
          onAnswered={onAnswered}
        />
      </div>
    </>
  );
}

function Chat({
  conversation,
  loading,
  loadError,
  enabled,
  tools,
  readOnly,
  onAnswered,
}: {
  conversation: Conversation | null;
  loading: boolean;
  loadError: string | null;
  enabled: boolean;
  tools: string[];
  readOnly: boolean;
  onAnswered: (c: Conversation) => void;
}) {
  const [text, setText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [pending, setPending] = useState<{ text: string; file: string | null } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const ask = useMutation({
    mutationFn: assistantApi.ask,
    onSuccess: (c) => {
      setText('');
      setFile(null);
      onAnswered(c);
    },
    onError: (e) => setProblem(errorMessage(e)),
    onSettled: () => setPending(null),
  });

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: 'end' });
  }, [conversation?.messages.length, pending]);

  const pick = (f: File | undefined) => {
    if (fileRef.current) fileRef.current.value = '';
    if (cameraRef.current) cameraRef.current.value = '';
    if (!f) return;
    const bad = checkFile(f);
    setProblem(bad);
    if (!bad) setFile(f);
  };

  const send = (q: string = text) => {
    if (ask.isPending || (!q.trim() && !file)) return;
    setProblem(null);
    setPending({ text: q.trim(), file: file?.name ?? null });
    ask.mutate({ text: q.trim(), conversationId: conversation?.id, file });
  };
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    send();
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const messages = conversation?.messages ?? [];
  const proposals = conversation?.proposals ?? [];
  const suggestions = SUGGESTIONS.filter((s) => tools.includes(s.needs)).slice(0, 5);

  return (
    <section className="flex min-h-[32rem] min-w-0 flex-col rounded-xl border border-gray-200 bg-white shadow-card" aria-label="Chat">
      <div className="flex-1 space-y-4 overflow-y-auto p-4 sm:p-5" aria-live="polite">
        {loading && <p className="text-sm text-gray-500"><Loader2 className="mr-1 inline h-4 w-4 animate-spin" />Loading…</p>}
        {loadError && <Alert tone="error">{loadError}</Alert>}
        {!loading && messages.length === 0 && !pending && (
          <div className="mx-auto max-w-xl py-6 text-center">
            <Bot className="mx-auto h-10 w-10 text-brand-600" aria-hidden />
            <h2 className="mt-3 text-base font-semibold text-gray-900">How can I help with the books today?</h2>
            <p className="mt-1 text-sm text-gray-500">
              Answers come from this shop’s own records. Attach a photo or PDF of a receipt or
              supplier invoice and I will read it and prepare the entry for you to confirm.
            </p>
            {enabled && suggestions.length > 0 && (
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                {suggestions.map((s) => (
                  <button key={s.text} type="button" onClick={() => send(s.text)}
                    className="rounded-full border border-gray-200 px-3 py-1.5 text-left text-sm text-gray-700 hover:border-brand-300 hover:bg-brand-50">
                    {s.text}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {messages.map((m) => (
          <Bubble key={m.id} m={m} proposals={proposals.filter((p) => p.message_id === m.id)} readOnly={readOnly} conversationId={conversation?.id ?? 0} />
        ))}
        {pending && (
          <>
            <div className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-brand-600 px-4 py-2.5 text-sm text-white">
              {pending.file && <p className="mb-1 flex items-center gap-1 text-xs text-brand-100"><Paperclip className="h-3.5 w-3.5" />{pending.file}</p>}
              {pending.text || 'Please read the attached file.'}
            </div>
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              {pending.file ? 'Reading the document and checking the records…' : 'Checking the records…'}
            </div>
          </>
        )}
        <div ref={endRef} />
      </div>

      {!readOnly && (
        <form onSubmit={onSubmit} className="border-t border-gray-100 p-3 sm:p-4">
          {problem && <div className="mb-2"><Alert tone="error">{problem}</Alert></div>}
          {file && (
            <div className="mb-2 flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2 text-sm">
              <FileText className="h-4 w-4 text-gray-500" aria-hidden />
              <span className="min-w-0 flex-1 truncate">{file.name}</span>
              <button type="button" onClick={() => setFile(null)} aria-label="Remove attachment" className="text-gray-500 hover:text-gray-800"><X className="h-4 w-4" /></button>
            </div>
          )}
          <div className="flex items-end gap-2">
            <Button type="button" variant="secondary" icon={<Paperclip className="h-4 w-4" />} aria-label="Attach a receipt or invoice" title="Attach a receipt or invoice (photo or PDF)" onClick={() => fileRef.current?.click()} disabled={!enabled || ask.isPending} className="shrink-0 px-3" />
            <Button type="button" variant="secondary" icon={<Camera className="h-4 w-4" />} aria-label="Take a photo of a receipt" onClick={() => cameraRef.current?.click()} disabled={!enabled || ask.isPending} className="shrink-0 px-3 sm:hidden" />
            <label htmlFor="assistant-question" className="sr-only">Your question</label>
            <textarea
              id="assistant-question"
              rows={2}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={onKey}
              maxLength={4000}
              disabled={!enabled}
              placeholder={enabled ? 'Ask about sales, profit, expenses or stock… (Enter to send)' : 'The assistant is not switched on'}
              className="min-h-[2.75rem] min-w-0 flex-1 resize-y rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 disabled:bg-gray-50"
            />
            <Button type="submit" icon={<Send className="h-4 w-4" />} loading={ask.isPending} disabled={!enabled || (!text.trim() && !file)} className="shrink-0">
              <span className="hidden sm:inline">Send</span>
            </Button>
          </div>
          <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp,application/pdf" className="sr-only" aria-label="Receipt or invoice file" tabIndex={-1} onChange={(e) => pick(e.target.files?.[0])} />
          <input ref={cameraRef} type="file" accept="image/*" capture="environment" className="sr-only" aria-label="Receipt photo" tabIndex={-1} onChange={(e) => pick(e.target.files?.[0])} />
          <p className="mt-2 text-xs text-gray-500">The AI can make mistakes: check figures before you confirm. Nothing is saved until you press Confirm.</p>
        </form>
      )}
    </section>
  );
}

function Bubble({ m, proposals, readOnly, conversationId }: { m: AssistantMessage; proposals: Proposal[]; readOnly: boolean; conversationId: number }) {
  if (m.role === 'user') {
    return (
      <div className="ml-auto max-w-[85%] space-y-2">
        {m.has_attachment && <Attachment m={m} />}
        {m.content && <div className="rounded-2xl rounded-br-sm bg-brand-600 px-4 py-2.5 text-sm text-white whitespace-pre-wrap break-words">{m.content}</div>}
      </div>
    );
  }
  return (
    <div className="max-w-[92%] space-y-2">
      <div className={clsx('rounded-2xl rounded-bl-sm px-4 py-2.5', m.error ? 'bg-red-50 text-red-800' : 'bg-gray-100 text-gray-900')}>
        {m.error ? <p className="text-sm">{m.error}</p> : <MessageText text={m.content} />}
      </div>
      {m.tool_log && m.tool_log.length > 0 && (
        <details className="text-xs text-gray-500">
          <summary className="cursor-pointer select-none"><Search className="mr-1 inline h-3.5 w-3.5" />Records checked ({m.tool_log.length})</summary>
          <ul className="mt-1 space-y-0.5 pl-5">
            {m.tool_log.map((t, i) => (
              <li key={i} className={t.ok ? '' : 'text-amber-700'}>
                {TOOL_LABEL[t.tool] ?? t.tool}
                {isPeriod(t.input) && ` · ${t.input.date_from} to ${t.input.date_to}`}
                {!t.ok && ` — ${t.summary}`}
              </li>
            ))}
          </ul>
        </details>
      )}
      {proposals.map((p) => <ProposalCard key={p.id} p={p} readOnly={readOnly} conversationId={conversationId} />)}
    </div>
  );
}

function isPeriod(v: unknown): v is { date_from: string; date_to: string } {
  return typeof v === 'object' && v !== null && 'date_from' in v && 'date_to' in v;
}

function Attachment({ m }: { m: AssistantMessage }) {
  const isImage = m.attachment_mime?.startsWith('image/');
  const blob = useQuery({ queryKey: ['assistant', 'attachment', m.id], queryFn: () => assistantApi.attachment(m.id), enabled: Boolean(isImage), staleTime: Infinity });
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!blob.data) return;
    const u = URL.createObjectURL(blob.data);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [blob.data]);
  if (isImage && url) {
    return <img src={url} alt={`Attached: ${m.attachment_name}`} className="ml-auto max-h-64 rounded-lg border border-gray-200" />;
  }
  return (
    <p className="ml-auto flex w-fit items-center gap-1.5 rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-800">
      <FileText className="h-4 w-4" aria-hidden />{m.attachment_name}
    </p>
  );
}

function ProposalCard({ p, readOnly, conversationId }: { p: Proposal; readOnly: boolean; conversationId: number }) {
  const qc = useQueryClient();
  const toast = useToast();
  const refresh = () => qc.invalidateQueries({ queryKey: ['assistant', 'conversation', conversationId] });
  const confirm = useMutation({
    mutationFn: () => assistantApi.confirm(p.id),
    onSuccess: () => {
      toast.success(p.kind === 'EXPENSE' ? 'Expense recorded' : 'Sent to invoice review');
      void qc.invalidateQueries({ queryKey: ['expenses'] });
      void qc.invalidateQueries({ queryKey: ['invoices'] });
      void refresh();
    },
    onError: (e) => toast.error('Not saved', errorMessage(e)),
  });
  const cancel = useMutation({ mutationFn: () => assistantApi.cancel(p.id), onSuccess: () => void refresh(), onError: (e) => toast.error('Could not cancel', errorMessage(e)) });
  const d = p.payload;
  return (
    <div className="rounded-xl border border-brand-200 bg-brand-50/50 p-4 text-sm">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="font-semibold text-gray-900">{p.kind === 'EXPENSE' ? 'Record this expense?' : 'Send this file to invoice review?'}</span>
        {p.status === 'CONFIRMED' && <Badge tone="green">Recorded</Badge>}
        {p.status === 'CANCELLED' && <Badge tone="gray">Cancelled</Badge>}
      </div>
      {p.kind === 'EXPENSE' ? (
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1">
          <dt className="text-gray-500">Amount</dt><dd className="font-semibold tabular-nums">{formatKES(String(d.amount))}</dd>
          <dt className="text-gray-500">Category</dt><dd>{String(d.category_name)}</dd>
          <dt className="text-gray-500">Date</dt><dd>{String(d.expense_date)}</dd>
          <dt className="text-gray-500">Paid by</dt><dd>{String(d.payment_method)}</dd>
          <dt className="text-gray-500">Description</dt><dd className="break-words">{String(d.description)}</dd>
          {d.reference && <><dt className="text-gray-500">Reference</dt><dd>{String(d.reference)}</dd></>}
        </dl>
      ) : (
        <p className="text-gray-700">
          <strong>{String(d.file)}</strong>{d.supplier ? ` from ${d.supplier}` : ''}{d.grand_total ? `, total ${formatKES(String(d.grand_total))}` : ''}.
          It will be read, matched to your products and wait for approval; stock changes only after approval.
        </p>
      )}
      {p.status === 'PENDING' && !readOnly && (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" icon={<CheckCircle2 className="h-4 w-4" />} loading={confirm.isPending} disabled={cancel.isPending} onClick={() => confirm.mutate()}>Confirm</Button>
          <Button size="sm" variant="secondary" icon={<XCircle className="h-4 w-4" />} loading={cancel.isPending} disabled={confirm.isPending} onClick={() => cancel.mutate()}>Cancel</Button>
        </div>
      )}
      {p.status === 'CONFIRMED' && p.result_id && (
        <p className="mt-2">
          <Link className="font-medium text-brand-700 hover:underline" to={p.kind === 'EXPENSE' ? '/expenses' : `/purchasing/invoices/${p.result_id}`}>
            {p.kind === 'EXPENSE' ? 'Open expenses' : 'Open the invoice review'}
          </Link>
        </p>
      )}
    </div>
  );
}

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Pencil, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';

import { financeApi, type ExpenseInput } from '@/api/finance';
import type { Expense } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { ActionMenu } from '@/components/ui/ActionMenu';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { DataTable, Pagination, type Column } from '@/components/ui/DataTable';
import { Input, Select, Textarea } from '@/components/ui/Field';
import { Modal } from '@/components/ui/Modal';
import { useToast } from '@/components/ui/Toast';
import { todayISO } from '@/features/sales/SalesPage';
import { errorMessage } from '@/lib/errors';
import { formatDate, formatKES } from '@/lib/format';

const PAY = [{ value: 'CASH', label: 'Cash' }, { value: 'MPESA', label: 'M-Pesa' }, { value: 'BANK', label: 'Bank transfer' }, { value: 'CARD', label: 'Card' }];
const control = 'h-10 rounded-lg border border-gray-300 bg-white px-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30';

function ExpenseModal({ expense, onClose, onSaved }: { expense: Expense | 'new'; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const cats = useQuery({ queryKey: ['expense-categories'], queryFn: financeApi.categories, staleTime: 600_000 });
  const e = expense === 'new' ? null : expense;
  const [form, setForm] = useState<ExpenseInput>({
    category_id: e?.category.id ?? 0, expense_date: e?.expense_date ?? todayISO(), amount: e ? String(Number(e.amount)) : '',
    description: e?.description ?? '', payment_method: e?.payment_method ?? 'CASH', reference: e?.reference ?? '',
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const amountOk = /^\d+(\.\d{1,2})?$/.test(form.amount.trim()) && Number(form.amount) > 0;
  const valid = form.category_id > 0 && amountOk && form.description.trim().length >= 2 && Boolean(form.expense_date);

  const save = async () => {
    setSaving(true);
    setError(null);
    const body = { ...form, amount: form.amount.trim(), description: form.description.trim(), reference: form.reference?.trim() || null };
    try {
      if (e) await financeApi.updateExpense(e.id, body);
      else await financeApi.createExpense(body);
      toast.success('Expense saved');
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open onClose={onClose} busy={saving} title={e ? 'Edit expense' : 'Record expense'}
      footer={<><Button variant="secondary" onClick={onClose} disabled={saving}>Cancel</Button><Button onClick={save} loading={saving} disabled={!valid}>Save</Button></>}>
      <div className="space-y-4">
        {error && <Alert tone="error">{error}</Alert>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Select label="Category" required placeholder="Choose…" value={form.category_id ? String(form.category_id) : ''} onChange={(ev) => setForm({ ...form, category_id: Number(ev.target.value) })}
            options={(cats.data ?? []).filter((c) => c.is_active).map((c) => ({ value: String(c.id), label: c.name }))} />
          <Input label="Date" type="date" required value={form.expense_date} onChange={(ev) => setForm({ ...form, expense_date: ev.target.value })} />
          <Input label="Amount (KES)" required inputMode="decimal" value={form.amount} error={form.amount && !amountOk ? 'Enter an amount like 4500 or 4500.50' : undefined} onChange={(ev) => setForm({ ...form, amount: ev.target.value })} />
          <Select label="Paid by" value={form.payment_method} onChange={(ev) => setForm({ ...form, payment_method: ev.target.value as ExpenseInput['payment_method'] })} options={PAY} />
        </div>
        <Textarea label="Description" required rows={2} value={form.description} onChange={(ev) => setForm({ ...form, description: ev.target.value })} placeholder="e.g. KPLC tokens for November" />
        <Input label="Reference" value={form.reference ?? ''} onChange={(ev) => setForm({ ...form, reference: ev.target.value })} hint="M-Pesa code, cheque or invoice number" />
      </div>
    </Modal>
  );
}

export function ExpensesPage() {
  const { can } = useAuth();
  const write = can(PERM.EXPENSES_WRITE);
  const toast = useToast();
  const qc = useQueryClient();
  const today = todayISO();
  const [from, setFrom] = useState(`${today.slice(0, 8)}01`);
  const [to, setTo] = useState(today);
  const [category, setCategory] = useState('');
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Expense | 'new' | null>(null);
  const [deleting, setDeleting] = useState<Expense | null>(null);
  const cats = useQuery({ queryKey: ['expense-categories'], queryFn: financeApi.categories, staleTime: 600_000 });
  const q = useQuery({
    queryKey: ['expenses', { from, to, category, page }],
    queryFn: () => financeApi.expenses({ date_from: from, date_to: to, category_id: category ? Number(category) : undefined, page, page_size: 25 }),
    placeholderData: keepPreviousData,
  });
  const del = useMutation({
    mutationFn: (id: number) => financeApi.deleteExpense(id),
    onSuccess: () => { toast.success('Expense deleted'); setDeleting(null); qc.invalidateQueries({ queryKey: ['expenses'] }); },
    onError: (err) => toast.error('Could not delete', errorMessage(err)),
  });
  const columns: Column<Expense>[] = [
    { key: 'd', header: 'Date', render: (e) => <span className="whitespace-nowrap">{formatDate(e.expense_date)}</span> },
    { key: 'c', header: 'Category', render: (e) => e.category.name },
    { key: 'x', header: 'Description', render: (e) => <span className="min-w-[10rem]">{e.description}{e.reference && <span className="block text-xs text-gray-500">Ref {e.reference}</span>}</span> },
    { key: 'a', header: 'Amount', className: 'text-right', render: (e) => <span className="whitespace-nowrap font-medium tabular-nums">{formatKES(e.amount)}</span> },
    { key: 'by', header: 'Recorded by', hideOnMobile: true, render: (e) => <span className="text-xs">{e.recorded_by.full_name}</span> },
    ...(write ? [{ key: 'act', header: <span className="sr-only">Actions</span>, className: 'w-12 text-right', render: (e: Expense) => (
      <ActionMenu label={`Actions for expense ${e.id}`} items={[
        { label: 'Edit', icon: <Pencil className="h-4 w-4" />, onClick: () => setEditing(e) },
        { label: 'Delete', icon: <Trash2 className="h-4 w-4" />, danger: true, onClick: () => setDeleting(e) },
      ]} />
    ) }] : []),
  ];
  const data = q.data;
  return (
    <>
      <PageHeader title="Expenses" description="Rent, wages, electricity and other running costs, used for the net profit estimate."
        actions={write && <Button icon={<Plus className="h-4 w-4" />} onClick={() => setEditing('new')}>Record expense</Button>} />
      <Card bodyClassName="p-0">
        <div className="flex flex-col gap-3 border-b border-gray-100 p-4 sm:flex-row sm:items-center">
          <div className="grid grid-cols-2 gap-3 sm:flex">
            <input type="date" aria-label="From" value={from} max={to} onChange={(e) => { setFrom(e.target.value); setPage(1); }} className={control} />
            <input type="date" aria-label="To" value={to} min={from} onChange={(e) => { setTo(e.target.value); setPage(1); }} className={control} />
          </div>
          <select aria-label="Category" value={category} onChange={(e) => { setCategory(e.target.value); setPage(1); }} className={control}>
            <option value="">All categories</option>
            {cats.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          {data && <p className="text-sm text-gray-600 sm:ml-auto">Total: <span className="font-semibold tabular-nums text-gray-900">{formatKES(data.total_amount)}</span></p>}
        </div>
        {q.isError ? <div className="p-4"><Alert tone="error">{errorMessage(q.error)}</Alert></div> : (
          <DataTable caption="Expenses" columns={columns} rows={data?.items ?? []} rowKey={(e) => e.id} loading={q.isFetching} emptyTitle="No expenses in this period" />
        )}
        {data && data.total > 0 && <Pagination page={data.page} pages={data.pages} total={data.total} pageSize={data.page_size} onPageChange={setPage} />}
      </Card>
      {editing && <ExpenseModal expense={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); qc.invalidateQueries({ queryKey: ['expenses'] }); }} />}
      <ConfirmDialog open={Boolean(deleting)} title="Delete this expense?" message={deleting ? `${deleting.description} (${formatKES(deleting.amount)}) will be removed. The deletion is recorded in the audit log.` : ''}
        confirmLabel="Delete" loading={del.isPending} onCancel={() => setDeleting(null)} onConfirm={() => deleting && del.mutate(deleting.id)} />
    </>
  );
}

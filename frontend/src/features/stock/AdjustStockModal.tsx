import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { stockApi } from '@/api/stock';
import type { AdjustmentReason, Batch, Product } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Checkbox, Input, Select, Textarea } from '@/components/ui/Field';
import { Modal } from '@/components/ui/Modal';
import { parseError } from '@/lib/errors';
import { formatDate, formatKES, formatQty, num, REASON_LABELS, WHOLE_UNITS } from '@/lib/format';

const schema = z
  .object({
    mode: z.enum(['count', 'change']),
    counted: z.string().optional(),
    direction: z.enum(['add', 'remove']),
    amount: z.string().optional(),
    reason_code: z.string(),
    notes: z.string().max(1000).optional(),
    expiry_date: z.string().optional(),
    batch_id: z.string().optional(),
    allow_negative: z.boolean(),
  })
  .superRefine((v, ctx) => {
    const field = v.mode === 'count' ? 'counted' : 'amount';
    const raw = (v.mode === 'count' ? v.counted : v.amount)?.trim() ?? '';
    if (!/^\d+(\.\d{1,3})?$/.test(raw)) {
      ctx.addIssue({ code: 'custom', path: [field], message: 'Enter a number like 12 or 2.5' });
    } else if (v.mode === 'change' && Number(raw) === 0) {
      ctx.addIssue({ code: 'custom', path: [field], message: 'Must be more than zero' });
    }
    if ((v.reason_code === 'OTHER' || v.reason_code === 'THEFT_SUSPECTED') && !v.notes?.trim()) {
      ctx.addIssue({ code: 'custom', path: ['notes'], message: 'Please explain this adjustment' });
    }
  });
type FormValues = z.infer<typeof schema>;

export function AdjustStockModal({
  open,
  product,
  batches,
  onClose,
  onDone,
}: {
  open: boolean;
  product: Product;
  batches: Batch[];
  onClose: () => void;
  onDone: (message: string, applied: boolean) => void;
}) {
  const { can } = useAuth();
  const canNegative = can(PERM.STOCK_ADJUST_NEGATIVE);
  const [formError, setFormError] = useState<string | null>(null);
  // The parent mounts this dialog only while it is open, so defaults apply on each open.
  // (No reset-on-prop-change: background refetches must never wipe what the user typed.)
  const {
    register,
    handleSubmit,
    watch,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      mode: 'count', direction: 'remove', reason_code: 'COUNT_CORRECTION', allow_negative: false,
      counted: '', amount: '', notes: '', expiry_date: '', batch_id: '',
    },
  });

  const v = watch();
  const unit = product.unit_of_measure;
  const onHand = num(product.quantity_on_hand);
  const change =
    v.mode === 'count'
      ? v.counted && !Number.isNaN(Number(v.counted)) ? Number(v.counted) - onHand : null
      : v.amount && !Number.isNaN(Number(v.amount)) ? (v.direction === 'add' ? 1 : -1) * Number(v.amount) : null;
  const after = change === null ? null : onHand + change;
  const cost = product.avg_cost !== undefined ? num(product.avg_cost) : null;
  const wholeOnly = WHOLE_UNITS.has(unit);
  const needsExpiry = product.tracks_expiry && change !== null && change > 0;

  const submit = async (values: FormValues) => {
    setFormError(null);
    if (wholeOnly && change !== null && !Number.isInteger(change)) {
      setError(values.mode === 'count' ? 'counted' : 'amount', { message: `${product.name} is counted in whole ${unit}` });
      return;
    }
    if (needsExpiry && !values.batch_id && !values.expiry_date) {
      setError('expiry_date', { message: 'Choose a batch or enter the expiry date' });
      return;
    }
    try {
      const res = await stockApi.adjust({
        product_id: product.id,
        ...(values.mode === 'count'
          ? { counted_quantity: values.counted }
          : { quantity_change: `${values.direction === 'add' ? '' : '-'}${values.amount}` }),
        reason_code: values.reason_code as AdjustmentReason,
        notes: values.notes?.trim() || null,
        batch_id: values.batch_id ? Number(values.batch_id) : null,
        expiry_date: needsExpiry && !values.batch_id ? values.expiry_date || null : null,
        allow_negative: values.allow_negative,
      });
      onDone(res.message, res.applied);
    } catch (err) {
      const parsed = parseError(err);
      if (parsed.fieldErrors.expiry_date) setError('expiry_date', { message: parsed.message });
      else setFormError(parsed.message);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      busy={isSubmitting}
      title={`Adjust stock: ${product.name}`}
      description={`System quantity: ${formatQty(product.quantity_on_hand, unit)}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>Cancel</Button>
          <Button type="submit" form="adjust-form" loading={isSubmitting}>Save adjustment</Button>
        </>
      }
    >
      <form id="adjust-form" onSubmit={handleSubmit(submit)} className="space-y-4" noValidate>
        {formError && <Alert tone="error">{formError}</Alert>}
        <div role="radiogroup" aria-label="Adjustment type" className="grid grid-cols-2 gap-2">
          {(
            [
              ['count', 'I counted the shelf', 'Enter what is physically there'],
              ['change', 'Add or remove', 'Enter how much changed'],
            ] as const
          ).map(([value, title, desc]) => (
            <label key={value} className={`cursor-pointer rounded-xl border p-3 text-sm ${v.mode === value ? 'border-brand-500 bg-brand-50/60 ring-1 ring-brand-500' : 'border-gray-200 hover:bg-gray-50'}`}>
              <input type="radio" value={value} className="sr-only" {...register('mode')} />
              <span className="block font-medium text-gray-900">{title}</span>
              <span className="text-xs text-gray-500">{desc}</span>
            </label>
          ))}
        </div>

        {v.mode === 'count' ? (
          <Input label={`Counted quantity (${unit})`} inputMode="decimal" autoFocus error={errors.counted?.message} {...register('counted')} />
        ) : (
          <div className="grid grid-cols-[auto_1fr] items-start gap-3">
            <Select label="Direction" options={[{ value: 'remove', label: 'Remove' }, { value: 'add', label: 'Add' }]} {...register('direction')} />
            <Input label={`Quantity (${unit})`} inputMode="decimal" error={errors.amount?.message} {...register('amount')} />
          </div>
        )}

        {change !== null && change !== 0 && (
          <div role="status" aria-label="Adjustment preview" className="rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-700">
            Change <span className={`font-semibold ${change > 0 ? 'text-brand-700' : 'text-red-600'}`}>{change > 0 ? '+' : '−'}{formatQty(Math.abs(change), unit)}</span>
            {' '}→ new balance <span className="font-semibold">{formatQty(after, unit)}</span>
            {cost !== null && <> · value {formatKES(Math.abs(change) * cost)}</>}
          </div>
        )}
        {after !== null && after < 0 && (
          <Alert tone="warning">
            This would make stock negative. {canNegative ? 'Tick the box below to authorise it.' : 'Only a Super Administrator can authorise negative stock.'}
          </Alert>
        )}

        <Select label="Reason" options={Object.entries(REASON_LABELS).map(([value, label]) => ({ value, label }))} {...register('reason_code')} />
        {batches.length > 0 && (
          <Select
            label="Batch (optional)"
            placeholder={change !== null && change < 0 ? 'Oldest expiry first (automatic)' : 'New batch'}
            options={batches.map((b) => ({ value: String(b.id), label: `${b.batch_number ?? `Batch #${b.id}`} · expires ${formatDate(b.expiry_date)} · ${formatQty(b.quantity_remaining)} left` }))}
            {...register('batch_id')}
          />
        )}
        {needsExpiry && !v.batch_id && (
          <Input label="Expiry date of this stock" type="date" required error={errors.expiry_date?.message} {...register('expiry_date')} />
        )}
        <Textarea label="Notes" rows={2} placeholder="What happened?" error={errors.notes?.message} {...register('notes')} />
        {canNegative && after !== null && after < 0 && (
          <Checkbox label="Authorise negative stock" description="Use only when sales were recorded before the stock was received." {...register('allow_negative')} />
        )}
        <p className="text-xs text-gray-500">Adjustments worth more than KES 5,000 at cost are sent to a Store Manager for approval.</p>
      </form>
    </Modal>
  );
}

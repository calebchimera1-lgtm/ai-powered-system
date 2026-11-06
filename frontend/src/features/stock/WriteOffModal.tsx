import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { stockApi } from '@/api/stock';
import type { Batch, Product } from '@/api/types';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Input, Select, Textarea } from '@/components/ui/Field';
import { Modal } from '@/components/ui/Modal';
import { errorMessage } from '@/lib/errors';
import { formatDate, formatKES, formatQty, WHOLE_UNITS } from '@/lib/format';

const schema = z.object({
  kind: z.enum(['DAMAGED', 'EXPIRED']),
  quantity: z.string().trim().regex(/^\d+(\.\d{1,3})?$/, 'Enter a number like 2 or 1.5').refine((v) => Number(v) > 0, 'Must be more than zero'),
  batch_id: z.string().optional(),
  notes: z.string().max(1000).optional(),
});
type FormValues = z.infer<typeof schema>;

export function WriteOffModal({
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
  onDone: (message: string) => void;
}) {
  const [formError, setFormError] = useState<string | null>(null);
  // Mounted only while open: defaults are computed once (see AdjustStockModal).
  const [expired] = useState(() => batches.find((b) => (b.days_to_expiry ?? 1) < 0));
  const { register, handleSubmit, watch, setError, formState: { errors, isSubmitting } } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { kind: expired ? 'EXPIRED' : 'DAMAGED', quantity: '', batch_id: expired ? String(expired.id) : '', notes: '' },
  });

  const kind = watch('kind');
  const unit = product.unit_of_measure;

  const submit = async (v: FormValues) => {
    setFormError(null);
    if (WHOLE_UNITS.has(unit) && !Number.isInteger(Number(v.quantity))) {
      setError('quantity', { message: `Use a whole number of ${unit}` });
      return;
    }
    try {
      const res = await stockApi.writeOff({
        product_id: product.id,
        quantity: v.quantity,
        kind: v.kind,
        batch_id: v.batch_id ? Number(v.batch_id) : null,
        notes: v.notes?.trim() || null,
      });
      onDone(
        `${formatQty(v.quantity, unit)} written off as ${v.kind === 'DAMAGED' ? 'damaged' : 'expired'}` +
          (res.value_lost ? ` (${formatKES(res.value_lost)} at cost)` : ''),
      );
    } catch (err) {
      setFormError(errorMessage(err));
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      busy={isSubmitting}
      title={`Write off: ${product.name}`}
      description={`In stock: ${formatQty(product.quantity_on_hand, unit)}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>Cancel</Button>
          <Button variant="danger" type="submit" form="writeoff-form" loading={isSubmitting}>Write off</Button>
        </>
      }
    >
      <form id="writeoff-form" onSubmit={handleSubmit(submit)} className="space-y-4" noValidate>
        {formError && <Alert tone="error">{formError}</Alert>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Select label="Reason" options={[{ value: 'DAMAGED', label: 'Damaged' }, { value: 'EXPIRED', label: 'Expired' }]} {...register('kind')} />
          <Input label={`Quantity (${unit})`} inputMode="decimal" autoFocus error={errors.quantity?.message} {...register('quantity')} />
        </div>
        {batches.length > 0 && (
          <Select
            label="Batch"
            placeholder="Oldest expiry first (automatic)"
            options={batches.map((b) => ({
              value: String(b.id),
              label: `${b.batch_number ?? `Batch #${b.id}`} · ${(b.days_to_expiry ?? 1) < 0 ? 'EXPIRED' : 'expires'} ${formatDate(b.expiry_date)} · ${formatQty(b.quantity_remaining)} left`,
            }))}
            {...register('batch_id')}
          />
        )}
        {kind === 'EXPIRED' && batches.length > 0 && (
          <p className="text-xs text-gray-500">Only batches past their expiry date can be written off as expired.</p>
        )}
        <Textarea label="Notes" rows={2} placeholder="e.g. Torn packaging, found on shelf" {...register('notes')} />
      </form>
    </Modal>
  );
}

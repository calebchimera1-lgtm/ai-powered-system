import { zodResolver } from '@hookform/resolvers/zod';
import { useEffect, useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import type { SupplierInput } from '@/api/catalog';
import type { Supplier } from '@/api/types';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Input, Textarea } from '@/components/ui/Field';
import { Modal } from '@/components/ui/Modal';
import { parseError } from '@/lib/errors';

const schema = z.object({
  name: z.string().trim().min(2, 'Enter the supplier name').max(150),
  kra_pin: z.string().trim().toUpperCase().regex(/^([AP]\d{9}[A-Z])?$/, 'A KRA PIN looks like P051234567X').optional(),
  contact_person: z.string().max(150).optional(),
  phone: z.string().trim().regex(/^(\+?[0-9 ]{7,20})?$/, 'Use a phone number such as +254712345678').optional(),
  email: z.union([z.literal(''), z.string().trim().email('Enter a valid email')]).optional(),
  address: z.string().max(500).optional(),
  payment_terms_days: z.coerce.number().int().min(0).max(365),
  notes: z.string().max(2000).optional(),
});
type FormValues = z.infer<typeof schema>;

export function SupplierFormModal({ open, supplier, onClose, onSave }: {
  open: boolean;
  supplier?: Supplier | null;
  onClose: () => void;
  onSave: (body: SupplierInput) => Promise<void>;
}) {
  const [formError, setFormError] = useState<string | null>(null);
  const { register, handleSubmit, reset, setError, formState: { errors, isSubmitting } } = useForm<FormValues>({ resolver: zodResolver(schema) });

  const supplierKey = supplier?.id ?? null;
  const latest = useRef(supplier);
  latest.current = supplier;
  useEffect(() => {
    const supplier = latest.current;
    if (open) {
      setFormError(null);
      reset({
        name: supplier?.name ?? '', kra_pin: supplier?.kra_pin ?? '', contact_person: supplier?.contact_person ?? '',
        phone: supplier?.phone ?? '', email: supplier?.email ?? '', address: supplier?.address ?? '',
        payment_terms_days: supplier?.payment_terms_days ?? 30, notes: supplier?.notes ?? '',
      });
    }
  }, [open, supplierKey, reset]);

  const submit = async (v: FormValues) => {
    setFormError(null);
    const blank = (s?: string) => (s && s.trim() ? s.trim() : null);
    try {
      await onSave({
        name: v.name, kra_pin: blank(v.kra_pin), contact_person: blank(v.contact_person), phone: blank(v.phone),
        email: blank(v.email), address: blank(v.address), payment_terms_days: v.payment_terms_days, notes: blank(v.notes),
      });
    } catch (err) {
      const parsed = parseError(err);
      let mapped = false;
      for (const [field, message] of Object.entries(parsed.fieldErrors)) {
        if (['name', 'kra_pin', 'phone', 'email'].includes(field)) {
          setError(field as keyof FormValues, { message: message.length > 3 ? parsed.message : message });
          mapped = true;
        }
      }
      if (!mapped) setFormError(parsed.message);
    }
  };

  return (
    <Modal open={open} onClose={onClose} busy={isSubmitting} title={supplier ? `Edit ${supplier.name}` : 'Add supplier'}
      footer={<>
        <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>Cancel</Button>
        <Button type="submit" form="supplier-form" loading={isSubmitting}>{supplier ? 'Save changes' : 'Add supplier'}</Button>
      </>}>
      <form id="supplier-form" onSubmit={handleSubmit(submit)} className="space-y-4" noValidate>
        {formError && <Alert tone="error">{formError}</Alert>}
        <Input label="Business name" required error={errors.name?.message} {...register('name')} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="KRA PIN" placeholder="P051234567X" autoCapitalize="characters" hint="Used to recognise their invoices" error={errors.kra_pin?.message} {...register('kra_pin')} />
          <Input label="Payment terms (days)" type="number" min={0} error={errors.payment_terms_days?.message} {...register('payment_terms_days')} />
          <Input label="Contact person" {...register('contact_person')} />
          <Input label="Phone" type="tel" placeholder="+254…" error={errors.phone?.message} {...register('phone')} />
        </div>
        <Input label="Email" type="email" error={errors.email?.message} {...register('email')} />
        <Textarea label="Address" rows={2} {...register('address')} />
        <Textarea label="Notes" rows={2} {...register('notes')} />
      </form>
    </Modal>
  );
}

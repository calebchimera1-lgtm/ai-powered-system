import { zodResolver } from '@hookform/resolvers/zod';
import { useEffect, useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import type { ProductInput } from '@/api/catalog';
import type { Product, Unit } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { ScanButton } from '@/components/ui/BarcodeScanner';
import { Button } from '@/components/ui/Button';
import { Checkbox, Input, Select, Textarea } from '@/components/ui/Field';
import { Modal } from '@/components/ui/Modal';
import { parseError } from '@/lib/errors';
import { UNIT_LABELS, WHOLE_UNITS } from '@/lib/format';

import { useCategories, useSupplierOptions } from './hooks';

const money = z
  .string()
  .trim()
  .regex(/^\d+(\.\d{1,2})?$/, 'Enter an amount like 245 or 245.50');
const qty = z
  .string()
  .trim()
  .regex(/^\d+(\.\d{1,3})?$/, 'Enter a number like 10 or 2.5');
const optionalQty = z.union([z.literal(''), qty]);

const schema = z
  .object({
    name: z.string().trim().min(2, 'Enter the product name').max(150),
    description: z.string().max(2000).optional(),
    sku: z.string().trim().max(40).optional(),
    barcode: z.string().trim().max(32).optional(),
    category_id: z.string().optional(),
    default_supplier_id: z.string().optional(),
    unit_of_measure: z.string(),
    selling_price: money,
    purchase_price: z.union([z.literal(''), money]).optional(),
    vat_rate: z.enum(['16', '8', '0']),
    min_stock_level: qty,
    max_stock_level: optionalQty,
    reorder_lead_time_days: z.coerce.number().int().min(0).max(365),
    tracks_expiry: z.boolean(),
    opening_qty: optionalQty.optional(),
    opening_cost: z.union([z.literal(''), money]).optional(),
    opening_expiry: z.string().optional(),
    opening_batch: z.string().max(50).optional(),
  })
  .superRefine((v, ctx) => {
    if (v.max_stock_level && Number(v.max_stock_level) < Number(v.min_stock_level)) {
      ctx.addIssue({ code: 'custom', path: ['max_stock_level'], message: 'Must be at least the minimum' });
    }
    const whole = WHOLE_UNITS.has(v.unit_of_measure);
    for (const f of ['min_stock_level', 'max_stock_level', 'opening_qty'] as const) {
      const val = v[f];
      if (whole && val && !Number.isInteger(Number(val))) {
        ctx.addIssue({ code: 'custom', path: [f], message: 'Use a whole number for this unit' });
      }
    }
    if (v.opening_qty && Number(v.opening_qty) > 0) {
      if (!v.opening_cost) ctx.addIssue({ code: 'custom', path: ['opening_cost'], message: 'Enter the unit cost' });
      if (v.tracks_expiry && !v.opening_expiry) {
        ctx.addIssue({ code: 'custom', path: ['opening_expiry'], message: 'Enter the expiry date' });
      }
    }
  });

type FormValues = z.infer<typeof schema>;

const FIELD_MAP: Record<string, keyof FormValues> = {
  'opening_stock.quantity': 'opening_qty',
  'opening_stock.unit_cost': 'opening_cost',
  'opening_stock.expiry_date': 'opening_expiry',
  expiry_date: 'opening_expiry',
};

function toForm(p?: Product | null): FormValues {
  return {
    name: p?.name ?? '',
    description: p?.description ?? '',
    sku: p?.sku ?? '',
    barcode: p?.barcode ?? '',
    category_id: p?.category ? String(p.category.id) : '',
    default_supplier_id: p?.default_supplier ? String(p.default_supplier.id) : '',
    unit_of_measure: p?.unit_of_measure ?? 'pcs',
    selling_price: p ? String(Number(p.selling_price)) : '',
    purchase_price: p?.purchase_price !== undefined ? String(Number(p.purchase_price)) : '',
    vat_rate: (p ? String(Number(p.vat_rate)) : '16') as FormValues['vat_rate'],
    min_stock_level: p ? String(Number(p.min_stock_level)) : '0',
    max_stock_level: p?.max_stock_level ? String(Number(p.max_stock_level)) : '',
    reorder_lead_time_days: p?.reorder_lead_time_days ?? 3,
    tracks_expiry: p?.tracks_expiry ?? false,
    opening_qty: '',
    opening_cost: '',
    opening_expiry: '',
    opening_batch: '',
  };
}

export function ProductFormModal({
  open,
  product,
  onClose,
  onSave,
}: {
  open: boolean;
  product?: Product | null;
  onClose: () => void;
  onSave: (body: ProductInput) => Promise<void>;
}) {
  const isEdit = Boolean(product);
  const { can } = useAuth();
  const canCost = can(PERM.PRODUCTS_VIEW_COST);
  const categories = useCategories();
  const suppliers = useSupplierOptions();
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    setError,
    setValue,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<z.input<typeof schema>, unknown, FormValues>({ resolver: zodResolver(schema), defaultValues: toForm(product) });

  // Reset when the dialog opens or a different product is loaded, but not when the same
  // product object is refreshed in the background (that would wipe the user's edits).
  const productKey = product?.id ?? null;
  const latest = useRef(product);
  latest.current = product;
  useEffect(() => {
    if (open) {
      setFormError(null);
      reset(toForm(latest.current));
    }
  }, [open, productKey, reset]);

  const unit = watch('unit_of_measure');
  const tracksExpiry = watch('tracks_expiry');
  const openingQty = watch('opening_qty');

  const submit = async (v: FormValues) => {
    setFormError(null);
    const body: ProductInput = {
      name: v.name,
      description: v.description?.trim() || null,
      sku: v.sku?.trim() || null,
      barcode: v.barcode?.trim() || null,
      category_id: v.category_id ? Number(v.category_id) : null,
      default_supplier_id: v.default_supplier_id ? Number(v.default_supplier_id) : null,
      unit_of_measure: v.unit_of_measure as Unit,
      selling_price: v.selling_price,
      vat_rate: v.vat_rate,
      min_stock_level: v.min_stock_level,
      max_stock_level: v.max_stock_level || null,
      reorder_lead_time_days: v.reorder_lead_time_days,
      tracks_expiry: v.tracks_expiry,
    };
    if (canCost && v.purchase_price) body.purchase_price = v.purchase_price;
    if (!isEdit && v.opening_qty && Number(v.opening_qty) > 0) {
      body.opening_stock = {
        quantity: v.opening_qty,
        unit_cost: v.opening_cost || '0',
        expiry_date: v.opening_expiry || null,
        batch_number: v.opening_batch?.trim() || null,
      };
    }
    if (isEdit) {
      // Never send an empty SKU on edit (the server keeps the existing one).
      if (!body.sku) delete body.sku;
    }
    try {
      await onSave(body);
    } catch (err) {
      const parsed = parseError(err);
      let mapped = false;
      for (const [field, message] of Object.entries(parsed.fieldErrors)) {
        const target = FIELD_MAP[field] ?? (field in toForm() ? (field as keyof FormValues) : null);
        if (target) {
          setError(target, { message: target === field ? message : parsed.message });
          mapped = true;
        }
      }
      if (!mapped) setFormError(parsed.message);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      busy={isSubmitting}
      size="lg"
      title={isEdit ? `Edit ${product?.name}` : 'Add product'}
      description={isEdit ? 'Stock quantities change only through receipts, sales and adjustments.' : undefined}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button type="submit" form="product-form" loading={isSubmitting}>
            {isEdit ? 'Save changes' : 'Add product'}
          </Button>
        </>
      }
    >
      <form id="product-form" onSubmit={handleSubmit(submit)} className="space-y-6" noValidate>
        {formError && <Alert tone="error">{formError}</Alert>}

        <section className="space-y-4">
          <h3 className="text-sm font-semibold text-gray-900">Product</h3>
          <Input label="Name" required placeholder="e.g. White Sugar 2kg" error={errors.name?.message} {...register('name')} />
          <div className="grid gap-4 sm:grid-cols-2">
            <Select
              label="Category"
              placeholder="No category"
              options={(categories.data ?? []).map((c) => ({ value: String(c.id), label: c.path }))}
              error={errors.category_id?.message}
              {...register('category_id')}
            />
            <Select
              label="Main supplier"
              placeholder="None"
              disabled={!suppliers.data}
              options={(suppliers.data ?? []).map((s) => ({ value: String(s.id), label: s.name }))}
              {...register('default_supplier_id')}
            />
          </div>
          <Textarea label="Description" rows={2} {...register('description')} />
        </section>

        <section className="space-y-4">
          <h3 className="text-sm font-semibold text-gray-900">Codes</h3>
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="SKU" hint={isEdit ? undefined : 'Leave blank to generate one'} autoCapitalize="characters" error={errors.sku?.message} {...register('sku')} />
            <div>
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <Input
                    label="Barcode"
                    inputMode="numeric"
                    hint="Scan the pack, or leave blank and generate one later"
                    error={errors.barcode?.message}
                    {...register('barcode')}
                  />
                </div>
                <div className={errors.barcode ? 'mb-6' : 'mb-5'}>
                  <ScanButton onDetected={(code) => setValue('barcode', code, { shouldDirty: true })} />
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="space-y-4">
          <h3 className="text-sm font-semibold text-gray-900">Price (KES)</h3>
          <div className="grid gap-4 sm:grid-cols-3">
            <Input label="Selling price" required inputMode="decimal" hint="Including VAT" error={errors.selling_price?.message} {...register('selling_price')} />
            <Select
              label="VAT rate"
              options={[
                { value: '16', label: '16% (standard)' },
                { value: '8', label: '8% (fuel)' },
                { value: '0', label: '0% (zero-rated / exempt)' },
              ]}
              {...register('vat_rate')}
            />
            {canCost && isEdit && (
              <Input label="Last purchase price" inputMode="decimal" hint="Updated automatically on receipt" error={errors.purchase_price?.message} {...register('purchase_price')} />
            )}
          </div>
        </section>

        <section className="space-y-4">
          <h3 className="text-sm font-semibold text-gray-900">Stock levels</h3>
          <div className="grid gap-4 sm:grid-cols-4">
            <Select
              label="Unit"
              options={Object.entries(UNIT_LABELS).map(([value, label]) => ({ value, label }))}
              {...register('unit_of_measure')}
            />
            <Input label="Minimum" inputMode="decimal" hint="Alert at or below" error={errors.min_stock_level?.message} {...register('min_stock_level')} />
            <Input label="Maximum" inputMode="decimal" hint="Optional" error={errors.max_stock_level?.message} {...register('max_stock_level')} />
            <Input label="Lead time (days)" type="number" min={0} error={errors.reorder_lead_time_days?.message} {...register('reorder_lead_time_days')} />
          </div>
          <Checkbox
            label="Track expiry dates"
            description="For perishables (milk, bread, yoghurt). Each delivery is kept as a batch and the oldest is used first."
            {...register('tracks_expiry')}
          />
        </section>

        {!isEdit && canCost && (
          <section className="space-y-4 rounded-xl border border-dashed border-gray-300 p-4">
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Opening stock (optional)</h3>
              <p className="text-xs text-gray-500">Stock already on the shelf when you start using the system.</p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Input label={`Quantity (${unit})`} inputMode="decimal" error={errors.opening_qty?.message} {...register('opening_qty')} />
              <Input label="Unit cost (KES)" inputMode="decimal" error={errors.opening_cost?.message} {...register('opening_cost')} />
              {tracksExpiry && openingQty && (
                <>
                  <Input label="Expiry date" type="date" required error={errors.opening_expiry?.message} {...register('opening_expiry')} />
                  <Input label="Batch / lot number" {...register('opening_batch')} />
                </>
              )}
            </div>
          </section>
        )}
      </form>
    </Modal>
  );
}

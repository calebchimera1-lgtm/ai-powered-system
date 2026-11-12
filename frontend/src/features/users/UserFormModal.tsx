import { zodResolver } from '@hookform/resolvers/zod';
import { useEffect, useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import type { RoleName, RoleOut, UserOut } from '@/api/types';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Field';
import { Modal } from '@/components/ui/Modal';
import { PASSWORD_HINT, newPasswordSchema } from '@/features/auth/passwordSchema';
import { parseError } from '@/lib/errors';

const ROLE_NAMES = ['super_admin', 'store_manager', 'inventory_officer', 'cashier'] as const;

const baseSchema = z.object({
  full_name: z.string().trim().min(2, 'Enter the full name').max(150),
  email: z.string().trim().email('Enter a valid email address'),
  phone: z
    .string()
    .trim()
    .regex(/^(\+?[0-9 ]{7,20})?$/, 'Use a phone number such as +254712345678')
    .optional(),
  role: z.enum(ROLE_NAMES, { error: 'Choose a role' }),
});

const createSchema = baseSchema.extend({
  username: z
    .string()
    .trim()
    .regex(/^[a-zA-Z0-9_.-]{3,50}$/, 'Use 3–50 letters, digits, dots, dashes or underscores'),
  passwordMode: z.enum(['link', 'set']),
  password: z.string().optional(),
}).superRefine((v, ctx) => {
  if (v.passwordMode === 'set') {
    const r = newPasswordSchema.safeParse(v.password ?? '');
    if (!r.success) ctx.addIssue({ code: 'custom', path: ['password'], message: r.error.issues[0]?.message });
  }
});

export type CreateValues = z.infer<typeof createSchema>;
export type EditValues = z.infer<typeof baseSchema>;

interface Props {
  open: boolean;
  roles: RoleOut[];
  user?: UserOut | null; // edit mode when provided
  currentUserId: number;
  onClose: () => void;
  onSubmit: (values: CreateValues | EditValues) => Promise<void>;
}

export function UserFormModal({ open, roles, user, currentUserId, onClose, onSubmit }: Props) {
  const isEdit = Boolean(user);
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    setError,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<CreateValues>({
    resolver: zodResolver(isEdit ? (baseSchema as unknown as typeof createSchema) : createSchema),
  });

  const userKey = user?.id ?? null;
  const latest = useRef(user);
  latest.current = user;
  useEffect(() => {
    if (!open) return;
    const user = latest.current;
    setFormError(null);
    reset(
      user
        ? { full_name: user.full_name, email: user.email, phone: user.phone ?? '', role: user.role.name }
        : { full_name: '', email: '', phone: '', role: 'cashier' as RoleName, username: '', passwordMode: 'link', password: '' },
    );
  }, [open, userKey, reset]);

  const passwordMode = watch('passwordMode');

  const submit = async (values: CreateValues) => {
    setFormError(null);
    try {
      await onSubmit(values);
    } catch (err) {
      const parsed = parseError(err);
      let mapped = false;
      for (const [field, message] of Object.entries(parsed.fieldErrors)) {
        if (['full_name', 'email', 'phone', 'role', 'username', 'password'].includes(field)) {
          setError(field as keyof CreateValues, { message });
          mapped = true;
        }
      }
      if (!mapped) setFormError(parsed.message);
    }
  };

  const editingSelf = user?.id === currentUserId;

  return (
    <Modal
      open={open}
      onClose={onClose}
      busy={isSubmitting}
      title={isEdit ? `Edit ${user?.full_name}` : 'Add staff member'}
      description={isEdit ? `Username: ${user?.username}` : 'They will sign in with their username or email.'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button type="submit" form="user-form" loading={isSubmitting}>
            {isEdit ? 'Save changes' : 'Create account'}
          </Button>
        </>
      }
    >
      <form id="user-form" onSubmit={handleSubmit(submit)} className="space-y-4" noValidate>
        {formError && <Alert tone="error">{formError}</Alert>}
        <Input label="Full name" required error={errors.full_name?.message} {...register('full_name')} />
        {!isEdit && (
          <Input
            label="Username"
            required
            autoCapitalize="none"
            hint="Lowercase letters and digits work best, e.g. jkamau"
            error={errors.username?.message}
            {...register('username')}
          />
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Email" type="email" required error={errors.email?.message} {...register('email')} />
          <Input label="Phone" type="tel" placeholder="+254…" error={errors.phone?.message} {...register('phone')} />
        </div>
        <Select
          label="Role"
          required
          disabled={editingSelf}
          hint={editingSelf ? 'You cannot change your own role.' : undefined}
          error={errors.role?.message}
          options={roles.map((r) => ({ value: r.name, label: `${r.display_name}: ${r.description}` }))}
          {...register('role')}
        />
        {!isEdit && (
          <fieldset className="space-y-3">
            <legend className="text-sm font-medium text-gray-700">First sign-in</legend>
            <label className="flex items-start gap-2 text-sm text-gray-700">
              <input type="radio" value="link" className="mt-0.5 text-brand-600" {...register('passwordMode')} />
              <span>
                Give them a one-time setup link <span className="text-gray-500">(recommended)</span>
              </span>
            </label>
            <label className="flex items-start gap-2 text-sm text-gray-700">
              <input type="radio" value="set" className="mt-0.5 text-brand-600" {...register('passwordMode')} />
              <span>Set a temporary password (they must change it when they first sign in)</span>
            </label>
            {passwordMode === 'set' && (
              <Input
                label="Temporary password"
                type="password"
                autoComplete="new-password"
                hint={PASSWORD_HINT}
                error={errors.password?.message}
                {...register('password')}
              />
            )}
          </fieldset>
        )}
      </form>
    </Modal>
  );
}

import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { authApi } from '@/api/auth';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Field';
import { parseError } from '@/lib/errors';

import { PASSWORD_HINT, newPasswordSchema } from './passwordSchema';

const schema = z
  .object({
    current_password: z.string().min(1, 'Enter your current password'),
    new_password: newPasswordSchema,
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, { path: ['confirm'], message: 'Passwords do not match' })
  .refine((v) => v.new_password !== v.current_password, {
    path: ['new_password'],
    message: 'Choose a different password from the current one',
  });
type FormValues = z.infer<typeof schema>;

export function ChangePasswordForm({ onDone, submitLabel = 'Change password' }: { onDone: () => void; submitLabel?: string }) {
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  const onSubmit = async (values: FormValues) => {
    setFormError(null);
    try {
      await authApi.changePassword(values.current_password, values.new_password);
      reset();
      onDone();
    } catch (err) {
      const parsed = parseError(err);
      const field = Object.keys(parsed.fieldErrors)[0];
      if (field === 'current_password' || field === 'new_password') {
        setError(field, { message: parsed.message });
      } else {
        setFormError(parsed.message);
      }
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
      {formError && <Alert tone="error">{formError}</Alert>}
      <Input
        label="Current password"
        type="password"
        autoComplete="current-password"
        error={errors.current_password?.message}
        {...register('current_password')}
      />
      <Input
        label="New password"
        type="password"
        autoComplete="new-password"
        hint={PASSWORD_HINT}
        error={errors.new_password?.message}
        {...register('new_password')}
      />
      <Input
        label="Confirm new password"
        type="password"
        autoComplete="new-password"
        error={errors.confirm?.message}
        {...register('confirm')}
      />
      <Button type="submit" loading={isSubmitting}>
        {submitLabel}
      </Button>
    </form>
  );
}

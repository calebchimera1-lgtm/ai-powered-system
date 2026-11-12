import { zodResolver } from '@hookform/resolvers/zod';
import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link, useSearchParams } from 'react-router-dom';
import { z } from 'zod';

import { authApi } from '@/api/auth';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Field';
import { parseError } from '@/lib/errors';

import { AuthLayout } from './AuthLayout';
import { PASSWORD_HINT, newPasswordSchema } from './passwordSchema';

const schema = z
  .object({ new_password: newPasswordSchema, confirm: z.string() })
  .refine((v) => v.new_password === v.confirm, { path: ['confirm'], message: 'Passwords do not match' });
type FormValues = z.infer<typeof schema>;

/** Landing page for one-time setup / reset links issued by an administrator. */
export function ResetPasswordPage() {
  const [params] = useSearchParams();
  // New links carry the token in the #fragment (never sent to the server, so never logged);
  // links issued before that change used ?token=, which still works.
  const [token] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('token') ?? params.get('token') ?? '');
  useEffect(() => {
    // Take the one-time token out of the address bar and browser history once it's been read.
    if (token) window.history.replaceState(window.history.state, '', window.location.pathname);
  }, [token]);
  const [done, setDone] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  const onSubmit = async (values: FormValues) => {
    setFormError(null);
    try {
      await authApi.resetPassword(token, values.new_password);
      setDone(true);
    } catch (err) {
      const parsed = parseError(err);
      if (parsed.fieldErrors.new_password) setError('new_password', { message: parsed.message });
      else setFormError(parsed.message);
    }
  };

  if (!token) {
    return (
      <AuthLayout title="Reset link missing">
        <Alert tone="error">This page needs the full link from your administrator.</Alert>
        <Link to="/login" className="mt-4 block text-center text-sm font-medium text-brand-700 hover:underline">
          Back to sign in
        </Link>
      </AuthLayout>
    );
  }

  if (done) {
    return (
      <AuthLayout title="Password set">
        <Alert tone="success">Your password has been saved. You can now sign in.</Alert>
        <Link
          to="/login"
          className="mt-4 flex h-10 items-center justify-center rounded-lg bg-brand-600 text-sm font-medium text-white hover:bg-brand-700"
        >
          Go to sign in
        </Link>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Choose a password" subtitle="This link works once and expires after 30 minutes.">
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        {formError && <Alert tone="error">{formError}</Alert>}
        <Input
          label="New password"
          type="password"
          autoComplete="new-password"
          hint={PASSWORD_HINT}
          error={errors.new_password?.message}
          {...register('new_password')}
        />
        <Input
          label="Confirm password"
          type="password"
          autoComplete="new-password"
          error={errors.confirm?.message}
          {...register('confirm')}
        />
        <Button type="submit" className="w-full" loading={isSubmitting}>
          Save password
        </Button>
      </form>
    </AuthLayout>
  );
}

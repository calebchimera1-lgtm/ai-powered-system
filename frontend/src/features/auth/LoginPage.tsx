import { zodResolver } from '@hookform/resolvers/zod';
import { LogIn } from 'lucide-react';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { z } from 'zod';

import { useAuth } from '@/auth/AuthProvider';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Field';
import { errorMessage } from '@/lib/errors';

import { AuthLayout } from './AuthLayout';

const schema = z.object({
  username: z.string().trim().min(1, 'Enter your username or email'),
  password: z.string().min(1, 'Enter your password'),
});
type FormValues = z.infer<typeof schema>;

export function LoginPage() {
  const { status, login, sessionExpired } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [formError, setFormError] = useState<string | null>(null);
  const from = (location.state as { from?: string } | null)?.from ?? '/';

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  if (status === 'authenticated') return <Navigate to={from} replace />;

  const onSubmit = async (values: FormValues) => {
    setFormError(null);
    try {
      const user = await login(values.username, values.password);
      navigate(user.must_change_password ? '/change-password' : from, { replace: true });
    } catch (err) {
      setFormError(errorMessage(err));
    }
  };

  return (
    <AuthLayout title="Sign in" subtitle="Use the account your administrator created for you.">
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        {sessionExpired && !formError && (
          <Alert tone="info">Your session ended. Please sign in again.</Alert>
        )}
        {formError && <Alert tone="error">{formError}</Alert>}
        <Input
          label="Username or email"
          autoComplete="username"
          autoCapitalize="none"
          autoFocus
          error={errors.username?.message}
          {...register('username')}
        />
        <Input
          label="Password"
          type="password"
          autoComplete="current-password"
          error={errors.password?.message}
          {...register('password')}
        />
        <Button type="submit" className="w-full" loading={isSubmitting} icon={<LogIn className="h-4 w-4" />}>
          Sign in
        </Button>
        <p className="text-center text-xs text-gray-500">
          Forgot your password? Ask a Super Administrator for a reset link.
        </p>
      </form>
    </AuthLayout>
  );
}

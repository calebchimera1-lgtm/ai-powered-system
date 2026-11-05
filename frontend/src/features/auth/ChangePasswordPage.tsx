import { useNavigate } from 'react-router-dom';

import { useAuth } from '@/auth/AuthProvider';
import { Alert } from '@/components/ui/Alert';
import { useToast } from '@/components/ui/Toast';

import { AuthLayout } from './AuthLayout';
import { ChangePasswordForm } from './ChangePasswordForm';

/** Shown right after signing in with a temporary password set by an administrator. */
export function ChangePasswordPage() {
  const { reloadUser, logout } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();

  return (
    <AuthLayout title="Set your own password" subtitle="Your administrator gave you a temporary password.">
      <div className="space-y-4">
        <Alert tone="info">Choose a new password before continuing.</Alert>
        <ChangePasswordForm
          submitLabel="Save and continue"
          onDone={async () => {
            await reloadUser();
            toast.success('Password changed');
            navigate('/', { replace: true });
          }}
        />
        <button
          type="button"
          onClick={async () => {
            await logout();
            navigate('/login', { replace: true });
          }}
          className="w-full text-center text-sm text-gray-500 hover:text-gray-700"
        >
          Sign out instead
        </button>
      </div>
    </AuthLayout>
  );
}

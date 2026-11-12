import { ShieldCheck } from 'lucide-react';
import { useState } from 'react';

import { authApi } from '@/api/auth';
import type { MfaSetup } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Input } from '@/components/ui/Field';
import { useToast } from '@/components/ui/Toast';
import { errorMessage } from '@/lib/errors';

const digitsOnly = (v: string) => v.replace(/\D/g, '').slice(0, 6);
/** "JBSWY3DPEHPK3PXP" -> "JBSW Y3DP EHPK 3PXP", easier to type into a phone. */
const grouped = (secret: string) => secret.replace(/(.{4})/g, '$1 ').trim();

/** Turn two-step sign-in (authenticator-app codes) on or off for your own account. */
export function TwoStepCard() {
  const { user, reloadUser } = useAuth();
  const toast = useToast();
  const [mode, setMode] = useState<'idle' | 'password' | 'scan' | 'disable'>('idle');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [setup, setSetup] = useState<MfaSetup | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const enabled = Boolean(user?.mfa_enabled);

  const reset = () => {
    setMode('idle');
    setPassword('');
    setCode('');
    setSetup(null);
    setError(null);
  };

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const start = () =>
    run(async () => {
      setSetup(await authApi.mfaSetup(password));
      setPassword('');
      setMode('scan');
    });

  const confirm = () =>
    run(async () => {
      await authApi.mfaEnable(code);
      await reloadUser();
      toast.success('Two-step sign-in is on', 'Your other devices were signed out.');
      reset();
    });

  const disable = () =>
    run(async () => {
      await authApi.mfaDisable(password, code);
      await reloadUser();
      toast.success('Two-step sign-in is off');
      reset();
    });

  return (
    <Card
      title="Two-step sign-in"
      description="After your password, also ask for a 6-digit code from an authenticator app on your phone."
      actions={<Badge tone={enabled ? 'green' : 'gray'}>{enabled ? 'On' : 'Off'}</Badge>}
    >
      {error && <div className="mb-4"><Alert tone="error">{error}</Alert></div>}

      {mode === 'idle' && (
        <div className="flex flex-wrap items-center gap-3">
          <p className="flex-1 text-sm text-gray-600">
            {enabled
              ? 'Someone who learns your password still cannot sign in without your phone.'
              : 'Recommended for administrators and managers. Works with Google Authenticator, Microsoft Authenticator, Authy and similar apps.'}
          </p>
          {enabled ? (
            <Button variant="secondary" onClick={() => setMode('disable')}>Turn off</Button>
          ) : (
            <Button icon={<ShieldCheck className="h-4 w-4" />} onClick={() => setMode('password')}>Set up</Button>
          )}
        </div>
      )}

      {mode === 'password' && (
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void start(); }}>
          <Input label="Your current password" type="password" autoComplete="current-password" required
            value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />
          <div className="flex gap-2">
            <Button type="submit" loading={busy} disabled={!password}>Continue</Button>
            <Button type="button" variant="ghost" onClick={reset}>Cancel</Button>
          </div>
        </form>
      )}

      {mode === 'scan' && setup && (
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void confirm(); }}>
          <ol className="list-decimal space-y-2 pl-5 text-sm text-gray-700">
            <li>
              In your authenticator app, add an account and choose to enter a key. On this phone you can instead{' '}
              <a href={setup.otpauth_uri} className="font-medium text-brand-700 hover:underline">open it in the app</a>.
            </li>
            <li>
              Enter this key (time-based):
              <code className="mt-1 block select-all break-all rounded-lg bg-gray-100 px-3 py-2 font-mono text-base tracking-wider text-gray-900">
                {grouped(setup.secret)}
              </code>
            </li>
            <li>Type the 6-digit code the app shows.</li>
          </ol>
          <Input label="Code from the app" inputMode="numeric" autoComplete="one-time-code" maxLength={6} required
            value={code} onChange={(e) => setCode(digitsOnly(e.target.value))} />
          <div className="flex gap-2">
            <Button type="submit" loading={busy} disabled={code.length !== 6}>Turn on</Button>
            <Button type="button" variant="ghost" onClick={reset}>Cancel</Button>
          </div>
        </form>
      )}

      {mode === 'disable' && (
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void disable(); }}>
          <Input label="Your current password" type="password" autoComplete="current-password" required
            value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />
          <Input label="Code from the app" inputMode="numeric" autoComplete="one-time-code" maxLength={6} required
            value={code} onChange={(e) => setCode(digitsOnly(e.target.value))} />
          <div className="flex gap-2">
            <Button type="submit" variant="danger" loading={busy} disabled={!password || code.length !== 6}>Turn off</Button>
            <Button type="button" variant="ghost" onClick={reset}>Cancel</Button>
          </div>
        </form>
      )}
    </Card>
  );
}

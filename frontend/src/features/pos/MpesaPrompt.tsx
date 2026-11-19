import { useMutation, useQuery } from '@tanstack/react-query';
import { CheckCircle2, Loader2, RotateCcw, Send, XCircle } from 'lucide-react';
import { useEffect, useState } from 'react';

import { salesApi } from '@/api/sales';
import type { MpesaPayment } from '@/api/types';
import { Button } from '@/components/ui/Button';
import { parseError } from '@/lib/errors';

/** Whole shillings, rounded up: M-Pesa does not take cents. */
export const mpesaAmount = (total: number) => Math.max(1, Math.ceil(total - 1e-9));
const PHONE_RE = /^(?:\+?254|0)?[17]\d{8}$/;

/**
 * Sends an M-Pesa payment prompt (STK push) to the customer's phone and follows it until the
 * customer pays, cancels or does not answer. Calls onChange with the payment as it changes.
 */
export function MpesaPrompt({
  total,
  payment,
  onChange,
  onEnterCodeInstead,
}: {
  total: number;
  payment: MpesaPayment | null;
  onChange: (p: MpesaPayment | null) => void;
  onEnterCodeInstead: () => void;
}) {
  const [phone, setPhone] = useState('');
  const [error, setError] = useState<string | null>(null);
  const amount = mpesaAmount(total);
  const cleaned = phone.replace(/[\s\-()]/g, '');
  const phoneOk = PHONE_RE.test(cleaned);

  const send = useMutation({
    mutationFn: () => salesApi.mpesaPrompt(cleaned, total.toFixed(2)),
    onSuccess: (p) => { setError(null); onChange(p); },
    onError: (err) => setError(parseError(err).message),
  });

  // Follow a pending prompt every 3 seconds; the server asks Safaricom for the result.
  const status = useQuery({
    queryKey: ['mpesa-payment', payment?.id],
    queryFn: () => salesApi.mpesaStatus(payment!.id),
    enabled: payment?.status === 'PENDING',
    refetchInterval: 3000,
    gcTime: 0,
  });
  useEffect(() => {
    if (status.data && payment && status.data.id === payment.id && status.data.status !== payment.status) onChange(status.data);
  }, [status.data, payment, onChange]);

  if (payment?.status === 'PENDING') {
    return (
      <div className="rounded-lg border border-brand-200 bg-brand-50 p-3 text-sm" role="status" aria-live="polite">
        <p className="flex items-center gap-2 font-semibold text-brand-800">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Prompt sent to {payment.phone}
        </p>
        <p className="mt-1 text-brand-800">Ask the customer to enter their M-Pesa PIN to pay KES {payment.amount.toLocaleString('en-KE')}.</p>
        <button type="button" onClick={() => onChange(null)} className="mt-2 py-1 text-xs font-medium text-gray-600 hover:underline">Cancel and start again</button>
      </div>
    );
  }
  if (payment?.status === 'SUCCESS') {
    const short = payment.amount < amount;
    return (
      <div className={`rounded-lg border p-3 text-sm ${short ? 'border-amber-300 bg-amber-50' : 'border-brand-300 bg-brand-50'}`} role="status" aria-live="polite">
        <p className="flex items-center gap-2 font-semibold text-brand-800">
          <CheckCircle2 className="h-4 w-4" aria-hidden /> Paid KES {payment.amount.toLocaleString('en-KE')}
          {payment.mpesa_receipt_number && <span className="font-mono">· {payment.mpesa_receipt_number}</span>}
        </p>
        {short ? (
          <p className="mt-1 text-amber-800">The cart changed: the total is now KES {amount.toLocaleString('en-KE')}. Remove the extra items or send a new prompt.</p>
        ) : (
          <p className="mt-1 text-brand-800">Complete the sale to print the receipt.</p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {payment && (
        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span><span className="font-semibold">Not paid.</span> {payment.result_desc}</span>
        </div>
      )}
      <label htmlFor="pos-mpesa-phone" className="block text-sm font-medium text-gray-700">Customer's M-Pesa number</label>
      <input id="pos-mpesa-phone" value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" autoComplete="off" placeholder="07XX XXX XXX"
        aria-invalid={phone !== '' && !phoneOk}
        className="h-11 w-full rounded-lg border border-gray-300 px-3 text-base tabular-nums focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30" />
      {phone !== '' && !phoneOk && <p className="text-xs text-red-600">Enter a Kenyan mobile number such as 0712 345 678.</p>}
      {error && <p className="text-sm text-red-600" role="alert">{error}</p>}
      <Button className="w-full" variant="secondary" disabled={!phoneOk || total <= 0} loading={send.isPending}
        icon={payment ? <RotateCcw className="h-4 w-4" /> : <Send className="h-4 w-4" />}
        onClick={() => send.mutate()}>
        {payment ? 'Send the prompt again' : 'Send payment prompt'} · KES {amount.toLocaleString('en-KE')}
      </Button>
      {amount !== Math.round(total * 100) / 100 && total > 0 && (
        <p className="text-xs text-gray-500">M-Pesa takes whole shillings, so KES {amount.toLocaleString('en-KE')} will be requested.</p>
      )}
      <button type="button" onClick={onEnterCodeInstead} className="py-1 text-xs font-medium text-brand-700 hover:underline">
        Customer already paid? Enter the M-Pesa code instead
      </button>
    </div>
  );
}

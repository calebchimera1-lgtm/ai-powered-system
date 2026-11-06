import { useMutation, useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { Banknote, CreditCard, Minus, Plus, Printer, ShoppingCart, Smartphone, Trash2, X } from 'lucide-react';
import { useMemo, useRef, useState } from 'react';

import { salesApi } from '@/api/sales';
import type { PaymentMethod, Product, Sale } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { ScanButton } from '@/components/ui/BarcodeScanner';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { ProductPicker } from '@/components/ui/ProductPicker';
import { useToast } from '@/components/ui/Toast';
import { printReceipt, Receipt } from '@/features/sales/Receipt';
import { productsApi } from '@/api/catalog';
import { parseError } from '@/lib/errors';
import { formatKES, formatQty, num, WHOLE_UNITS } from '@/lib/format';
import { priceCart } from '@/lib/pricing';

interface CartLine {
  product: Product;
  quantity: string; // text so cashiers can type "1.25"
}

const METHODS: { value: PaymentMethod; label: string; icon: typeof Banknote }[] = [
  { value: 'CASH', label: 'Cash', icon: Banknote },
  { value: 'MPESA', label: 'M-Pesa', icon: Smartphone },
  { value: 'CARD', label: 'Card', icon: CreditCard },
];

/** UUID v4. crypto.randomUUID needs HTTPS or localhost; a till on the shop's Wi-Fi over
 * plain http may not have it, so fall back to getRandomValues (available everywhere). */
export function newRequestId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6]! & 0x0f) | 0x40;
  b[8] = (b[8]! & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

export function PosPage() {
  const { can } = useAuth();
  const toast = useToast();
  const pickerRef = useRef<HTMLInputElement>(null);
  const [cart, setCart] = useState<CartLine[]>([]);
  const [discountText, setDiscountText] = useState('');
  const [discountMode, setDiscountMode] = useState<'amount' | 'percent'>('amount');
  const [method, setMethod] = useState<PaymentMethod>('CASH');
  const [tendered, setTendered] = useState('');
  const [reference, setReference] = useState('');
  const [phone, setPhone] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [completed, setCompleted] = useState<Sale | null>(null);
  // One id per attempt: retries of the same checkout can never record two sales.
  const requestId = useRef(newRequestId());

  const store = useQuery({ queryKey: ['store'], queryFn: salesApi.store, staleTime: 10 * 60_000 });
  const limit = num(store.data?.max_cashier_discount_percent ?? 10);

  const priced = useMemo(() => {
    const lines = cart.map((l) => ({ quantity: num(l.quantity), unitPrice: num(l.product.selling_price), vatRate: num(l.product.vat_rate) }));
    const preview = priceCart(lines, 0);
    const raw = num(discountText);
    const amount = discountMode === 'percent' ? Math.round(preview.subtotal * raw) / 100 : raw;
    return { ...priceCart(lines, Math.min(amount, preview.subtotal)), discountAmount: Math.min(amount, preview.subtotal) };
  }, [cart, discountText, discountMode]);

  const discountPct = priced.subtotal > 0 ? (priced.discountAmount / priced.subtotal) * 100 : 0;
  const overLimit = discountPct > limit + 1e-9 && !can(PERM.SALES_DISCOUNT_ANY);
  const change = method === 'CASH' && tendered ? num(tendered) - priced.total : null;

  const add = (product: Product) => {
    setError(null);
    setCart((lines) => {
      const i = lines.findIndex((l) => l.product.id === product.id);
      if (i >= 0) {
        const next = [...lines];
        next[i] = { ...next[i]!, quantity: String(num(next[i]!.quantity) + 1) };
        return next;
      }
      return [...lines, { product, quantity: '1' }];
    });
    pickerRef.current?.focus();
  };

  const setQty = (id: number, value: string) =>
    setCart((lines) => lines.map((l) => (l.product.id === id ? { ...l, quantity: value } : l)));
  const remove = (id: number) => setCart((lines) => lines.filter((l) => l.product.id !== id));

  const reset = () => {
    setCart([]);
    setDiscountText('');
    setTendered('');
    setReference('');
    setPhone('');
    setMethod('CASH');
    setError(null);
    requestId.current = newRequestId();
  };

  const lineProblem = (l: CartLine): string | null => {
    const q = num(l.quantity);
    if (!(q > 0)) return 'Enter a quantity';
    if (WHOLE_UNITS.has(l.product.unit_of_measure) && !Number.isInteger(q)) return 'Whole numbers only';
    if (q > num(l.product.quantity_on_hand)) return `Only ${formatQty(l.product.quantity_on_hand, l.product.unit_of_measure)} in stock`;
    return null;
  };
  const problems = cart.map(lineProblem);
  const canPay =
    cart.length > 0 &&
    problems.every((p) => p === null) &&
    !overLimit &&
    (method !== 'CASH' || (change !== null && change >= 0)) &&
    (method !== 'MPESA' || /^[A-Z0-9]{10}$/.test(reference.trim().toUpperCase()));

  const checkout = useMutation({
    mutationFn: () =>
      salesApi.checkout({
        client_request_id: requestId.current,
        items: cart.map((l) => ({ product_id: l.product.id, quantity: String(num(l.quantity)) })),
        cart_discount: priced.discountAmount > 0 ? priced.discountAmount.toFixed(2) : undefined,
        payment_method: method,
        amount_tendered: method === 'CASH' ? num(tendered).toFixed(2) : null,
        payment_reference: method === 'CASH' ? null : reference.trim().toUpperCase() || null,
        customer_phone: phone.trim() || null,
      }),
    onSuccess: (sale) => {
      setCompleted(sale);
      reset();
    },
    onError: (err) => setError(parseError(err).message),
  });

  const quickCash = useMemo(() => {
    const t = priced.total;
    if (t <= 0) return [];
    const ups = [50, 100, 500, 1000].map((step) => Math.ceil(t / step) * step);
    return Array.from(new Set([t, ...ups])).slice(0, 4);
  }, [priced.total]);

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_22rem] xl:grid-cols-[1fr_24rem]">
      {/* Cart */}
      <section aria-label="Cart" className="flex min-h-[60vh] flex-col rounded-xl border border-gray-200 bg-white shadow-card">
        <div className="flex gap-2 border-b border-gray-100 p-3 sm:p-4">
          <div className="flex-1">
            <ProductPicker
              ref={pickerRef}
              autoFocus
              onPick={add}
              onNotFound={(code) => toast.info('Product not found', `No product matches "${code}".`)}
            />
          </div>
          <ScanButton
            onDetected={async (code) => {
              try {
                add((await productsApi.lookup(code)).product);
              } catch {
                toast.info('Product not found', `No product has the barcode ${code}.`);
              }
            }}
          />
        </div>

        {cart.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center p-8 text-center text-gray-500">
            <ShoppingCart className="mb-3 h-10 w-10 text-gray-300" aria-hidden />
            <p className="font-medium text-gray-700">Scan or search for a product to start a sale</p>
            <p className="mt-1 text-sm">USB scanners work directly: just scan into the search box.</p>
          </div>
        ) : (
          <ul className="flex-1 divide-y divide-gray-100 overflow-y-auto">
            {cart.map((l, i) => {
              const whole = WHOLE_UNITS.has(l.product.unit_of_measure);
              const step = whole ? 1 : 0.25;
              return (
                <li key={l.product.id} className="flex flex-wrap items-center gap-3 px-3 py-3 sm:px-4">
                  <div className="min-w-0 basis-full sm:basis-0 sm:flex-1">
                    <p className="font-medium text-gray-900 sm:truncate">{l.product.name}</p>
                    <p className="text-xs text-gray-500">
                      {formatKES(l.product.selling_price)} / {l.product.unit_of_measure}
                    </p>
                    {problems[i] && <p className="mt-0.5 text-xs font-medium text-red-600">{problems[i]}</p>}
                  </div>
                  <div className="flex items-center gap-1">
                    <button type="button" aria-label={`Fewer ${l.product.name}`} onClick={() => setQty(l.product.id, String(Math.max(num(l.quantity) - step, step)))}
                      className="rounded-lg border border-gray-300 p-2 hover:bg-gray-50"><Minus className="h-4 w-4" /></button>
                    <input
                      value={l.quantity}
                      onChange={(e) => setQty(l.product.id, e.target.value)}
                      inputMode="decimal"
                      aria-label={`Quantity of ${l.product.name}`}
                      className={clsx('h-9 w-16 rounded-lg border text-center text-sm tabular-nums focus:outline-none focus:ring-2', problems[i] ? 'border-red-400 focus:ring-red-500/30' : 'border-gray-300 focus:ring-brand-500/30')}
                    />
                    <button type="button" aria-label={`More ${l.product.name}`} onClick={() => setQty(l.product.id, String(num(l.quantity) + step))}
                      className="rounded-lg border border-gray-300 p-2 hover:bg-gray-50"><Plus className="h-4 w-4" /></button>
                  </div>
                  <p className="ml-auto w-24 text-right font-semibold tabular-nums text-gray-900">{formatKES(priced.lines[i]?.total ?? 0)}</p>
                  <button type="button" aria-label={`Remove ${l.product.name}`} onClick={() => remove(l.product.id)}
                    className="rounded-lg p-2 text-gray-400 hover:bg-red-50 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
                </li>
              );
            })}
          </ul>
        )}
        {cart.length > 0 && (
          <div className="border-t border-gray-100 p-3 text-right sm:p-4">
            <Button variant="ghost" size="sm" icon={<X className="h-4 w-4" />} onClick={reset}>Clear sale</Button>
          </div>
        )}
      </section>

      {/* Payment */}
      <section aria-label="Payment" className="space-y-4 rounded-xl border border-gray-200 bg-white p-4 shadow-card lg:sticky lg:top-20 lg:self-start">
        <dl className="space-y-1.5 text-sm">
          <div className="flex justify-between"><dt className="text-gray-500">Subtotal</dt><dd className="tabular-nums">{formatKES(priced.subtotal)}</dd></div>
          {priced.discount > 0 && <div className="flex justify-between text-brand-700"><dt>Discount</dt><dd className="tabular-nums">−{formatKES(priced.discount)}</dd></div>}
          <div className="flex items-baseline justify-between border-t border-gray-100 pt-2">
            <dt className="text-base font-semibold text-gray-900">Total</dt>
            <dd className="text-3xl font-bold tabular-nums text-gray-900" data-testid="pos-total">{formatKES(priced.total)}</dd>
          </div>
          <div className="flex justify-between text-xs text-gray-500"><dt>VAT included</dt><dd className="tabular-nums">{formatKES(priced.vat)}</dd></div>
        </dl>

        <div>
          <label htmlFor="pos-discount" className="mb-1.5 block text-sm font-medium text-gray-700">Discount</label>
          <div className="flex gap-2">
            <input id="pos-discount" value={discountText} onChange={(e) => setDiscountText(e.target.value)} inputMode="decimal" placeholder="0"
              className="h-10 min-w-0 flex-1 rounded-lg border border-gray-300 px-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30" />
            <div role="group" aria-label="Discount type" className="flex rounded-lg bg-gray-100 p-1">
              {(['amount', 'percent'] as const).map((m) => (
                <button key={m} type="button" aria-pressed={discountMode === m} onClick={() => setDiscountMode(m)}
                  className={`rounded-md px-3 text-sm font-medium ${discountMode === m ? 'bg-white shadow-sm' : 'text-gray-600'}`}>
                  {m === 'amount' ? 'KES' : '%'}
                </button>
              ))}
            </div>
          </div>
          {overLimit && <p className="mt-1 text-xs text-red-600">Discounts above {limit}% need a Store Manager.</p>}
        </div>

        <div role="radiogroup" aria-label="Payment method" className="grid grid-cols-3 gap-2">
          {METHODS.map(({ value, label, icon: Icon }) => (
            <button key={value} type="button" role="radio" aria-checked={method === value} onClick={() => setMethod(value)}
              className={clsx('flex flex-col items-center gap-1 rounded-xl border px-2 py-2.5 text-sm font-medium', method === value ? 'border-brand-500 bg-brand-50 text-brand-800 ring-1 ring-brand-500' : 'border-gray-200 text-gray-700 hover:bg-gray-50')}>
              <Icon className="h-5 w-5" aria-hidden />
              {label}
            </button>
          ))}
        </div>

        {method === 'CASH' && (
          <div className="space-y-2">
            <label htmlFor="pos-cash" className="block text-sm font-medium text-gray-700">Cash received</label>
            <input id="pos-cash" value={tendered} onChange={(e) => setTendered(e.target.value)} inputMode="decimal" placeholder="0.00"
              className="h-12 w-full rounded-lg border border-gray-300 px-3 text-lg tabular-nums focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30" />
            <div className="flex flex-wrap gap-1.5">
              {quickCash.map((v) => (
                <button key={v} type="button" onClick={() => setTendered(v.toFixed(2))} className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs font-medium tabular-nums hover:bg-gray-50">
                  {v === priced.total ? 'Exact' : v.toLocaleString('en-KE')}
                </button>
              ))}
            </div>
            {change !== null && (
              <p className={clsx('rounded-lg px-3 py-2 text-sm font-semibold', change >= 0 ? 'bg-brand-50 text-brand-800' : 'bg-red-50 text-red-700')}>
                {change >= 0 ? `Change: ${formatKES(change)}` : `Short by ${formatKES(-change)}`}
              </p>
            )}
          </div>
        )}
        {method === 'MPESA' && (
          <div>
            <label htmlFor="pos-ref" className="mb-1.5 block text-sm font-medium text-gray-700">M-Pesa transaction code</label>
            <input id="pos-ref" value={reference} onChange={(e) => setReference(e.target.value.toUpperCase())} maxLength={10} placeholder="e.g. SKD4H2L9QX" autoCapitalize="characters"
              className="h-10 w-full rounded-lg border border-gray-300 px-3 font-mono text-sm uppercase focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30" />
            <p className="mt-1 text-xs text-gray-500">From the customer's confirmation SMS (10 letters and digits).</p>
          </div>
        )}
        {method === 'CARD' && (
          <div>
            <label htmlFor="pos-card" className="mb-1.5 block text-sm font-medium text-gray-700">Card approval code (optional)</label>
            <input id="pos-card" value={reference} onChange={(e) => setReference(e.target.value)} maxLength={20}
              className="h-10 w-full rounded-lg border border-gray-300 px-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30" />
          </div>
        )}
        <div>
          <label htmlFor="pos-phone" className="mb-1.5 block text-sm font-medium text-gray-700">Customer phone (optional)</label>
          <input id="pos-phone" value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" placeholder="07…"
            className="h-10 w-full rounded-lg border border-gray-300 px-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30" />
        </div>

        {error && <Alert tone="error">{error}</Alert>}
        <Button className="h-14 w-full text-base" disabled={!canPay} loading={checkout.isPending} onClick={() => { setError(null); checkout.mutate(); }}>
          Complete sale {priced.total > 0 && `· ${formatKES(priced.total)}`}
        </Button>
      </section>

      <Modal open={Boolean(completed)} onClose={() => { setCompleted(null); pickerRef.current?.focus(); }} title="Sale complete" size="sm"
        description={completed?.change_given && Number(completed.change_given) > 0 ? `Give change: ${formatKES(completed.change_given)}` : undefined}
        footer={<>
          <Button variant="secondary" icon={<Printer className="h-4 w-4" />} onClick={() => completed && printReceipt(completed, store.data)}>Print receipt</Button>
          <Button data-autofocus onClick={() => { setCompleted(null); pickerRef.current?.focus(); }}>New sale</Button>
        </>}>
        {completed && <Receipt sale={completed} store={store.data} />}
      </Modal>
    </div>
  );
}

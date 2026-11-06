import type { Sale, StoreInfo } from '@/api/types';
import { formatDateTime, formatKES, formatQty } from '@/lib/format';

const METHOD: Record<string, string> = { CASH: 'Cash', MPESA: 'M-Pesa', CARD: 'Card' };

/** On-screen receipt, laid out like an 80 mm till roll. */
export function Receipt({ sale, store }: { sale: Sale; store?: StoreInfo }) {
  return (
    <div className="mx-auto w-full max-w-xs rounded-lg border border-dashed border-gray-300 bg-white p-4 font-mono text-xs text-gray-900">
      <div className="text-center">
        <p className="text-sm font-bold">{store?.name}</p>
        {store?.address && <p>{store.address}</p>}
        {store?.phone && <p>Tel {store.phone}</p>}
        {store?.kra_pin && <p>PIN {store.kra_pin}</p>}
      </div>
      <div className="my-2 border-t border-dashed border-gray-300" />
      <p>Receipt: {sale.receipt_number}</p>
      <p>Date: {formatDateTime(sale.sold_at)}</p>
      <p>Served by: {sale.cashier.full_name}</p>
      <div className="my-2 border-t border-dashed border-gray-300" />
      <table className="w-full">
        <tbody>
          {sale.items.map((i) => (
            <tr key={i.id} className="align-top">
              <td className="pb-1 pr-2">
                {i.product_name}
                <br />
                <span className="text-gray-500">
                  {formatQty(i.quantity)} x {Number(i.unit_price).toFixed(2)}
                  {Number(i.discount_amount) > 0 && ` −${Number(i.discount_amount).toFixed(2)}`}
                </span>
              </td>
              <td className="pb-1 text-right tabular-nums">{Number(i.line_total).toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="my-2 border-t border-dashed border-gray-300" />
      <Line label="Subtotal" value={sale.subtotal} />
      {Number(sale.discount_total) > 0 && <Line label="Discount" value={`-${sale.discount_total}`} />}
      <Line label="TOTAL" value={sale.grand_total} bold />
      <Line label="VAT included" value={sale.tax_total} />
      <div className="my-2 border-t border-dashed border-gray-300" />
      <Line label={`Paid (${METHOD[sale.payment_method]})`} value={sale.amount_tendered ?? sale.grand_total} />
      {sale.change_given !== null && <Line label="Change" value={sale.change_given} />}
      {sale.payment_reference && <p>Ref: {sale.payment_reference}</p>}
      <div className="my-2 border-t border-dashed border-gray-300" />
      <p className="text-center">{store?.receipt_footer}</p>
    </div>
  );
}

function Line({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <div className={`flex justify-between ${bold ? 'text-sm font-bold' : ''}`}>
      <span>{label}</span>
      <span className="tabular-nums">{formatKES(value)}</span>
    </div>
  );
}

/** Prints the receipt in a small window (built with DOM calls, so it works under the CSP). */
export function printReceipt(sale: Sale, store?: StoreInfo): void {
  const w = window.open('', '_blank', 'width=360,height=640');
  if (!w) return;
  const d = w.document;
  d.title = sale.receipt_number;
  d.body.style.cssText = 'font-family:monospace;font-size:12px;width:72mm;margin:4mm';
  const add = (text: string, css = '') => {
    const el = d.createElement('div');
    el.textContent = text;
    el.style.cssText = css;
    d.body.append(el);
  };
  const row = (left: string, right: string, css = '') => {
    const el = d.createElement('div');
    el.style.cssText = `display:flex;justify-content:space-between;${css}`;
    const a = d.createElement('span');
    a.textContent = left;
    const b = d.createElement('span');
    b.textContent = right;
    el.append(a, b);
    d.body.append(el);
  };
  const rule = () => add('-'.repeat(40), 'overflow:hidden;white-space:nowrap');
  const center = 'text-align:center';
  if (store) {
    add(store.name, `${center};font-weight:bold;font-size:14px`);
    if (store.address) add(store.address, center);
    if (store.phone) add(`Tel ${store.phone}`, center);
    if (store.kra_pin) add(`PIN ${store.kra_pin}`, center);
  }
  rule();
  add(`Receipt: ${sale.receipt_number}`);
  add(`Date: ${formatDateTime(sale.sold_at)}`);
  add(`Served by: ${sale.cashier.full_name}`);
  rule();
  for (const i of sale.items) {
    add(i.product_name);
    row(`  ${formatQty(i.quantity)} x ${Number(i.unit_price).toFixed(2)}`, Number(i.line_total).toFixed(2));
  }
  rule();
  row('Subtotal', formatKES(sale.subtotal));
  if (Number(sale.discount_total) > 0) row('Discount', `-${formatKES(sale.discount_total)}`);
  row('TOTAL', formatKES(sale.grand_total), 'font-weight:bold;font-size:14px');
  row('VAT included', formatKES(sale.tax_total));
  rule();
  row(`Paid (${METHOD[sale.payment_method]})`, formatKES(sale.amount_tendered ?? sale.grand_total));
  if (sale.change_given !== null) row('Change', formatKES(sale.change_given));
  if (sale.payment_reference) add(`Ref: ${sale.payment_reference}`);
  rule();
  if (store?.receipt_footer) add(store.receipt_footer, center);
  w.focus();
  w.print();
}

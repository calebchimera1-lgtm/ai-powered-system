import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { purchasingApi } from '@/api/purchasing';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { Input, Select, Textarea } from '@/components/ui/Field';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { useSupplierOptions } from '@/features/products/hooks';
import { errorMessage, parseError } from '@/lib/errors';

import { type EditLine, LinesEditor, lineProblems } from './LinesEditor';

/** Record a supplier delivery: stock, average cost, batches and supplier prices update. */
export function ReceiveGoodsPage() {
  const [params] = useSearchParams();
  const poId = params.get('po') ? Number(params.get('po')) : null;
  const navigate = useNavigate();
  const toast = useToast();
  const qc = useQueryClient();
  const suppliers = useSupplierOptions();
  const po = useQuery({ queryKey: ['purchase-order', poId], queryFn: () => purchasingApi.order(poId!), enabled: poId !== null });
  const [supplierId, setSupplierId] = useState('');
  const [invoice, setInvoice] = useState('');
  const [invoiceDate, setInvoiceDate] = useState('');
  const [notes, setNotes] = useState('');
  const [lines, setLines] = useState<EditLine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [prefilled, setPrefilled] = useState(false);

  useEffect(() => {
    if (!po.data || prefilled) return;
    setSupplierId(String(po.data.supplier.id));
    setLines(
      po.data.items
        .filter((i) => Number(i.quantity_received) < Number(i.quantity_ordered))
        .map((i) => {
          const left = Number(i.quantity_ordered) - Number(i.quantity_received);
          return { product: i.product, quantity: String(left), unit_cost: String(Number(i.unit_cost)), max: left };
        }),
    );
    setPrefilled(true);
  }, [po.data, prefilled]);

  if (poId && po.isLoading) return <div className="flex justify-center py-20"><Spinner label="Loading…" /></div>;
  const problems = lineProblems(lines, true);

  const save = async () => {
    setError(null);
    setSaving(true);
    try {
      const grn = await purchasingApi.receive({
        supplier_id: Number(supplierId),
        purchase_order_id: poId,
        supplier_invoice_number: invoice.trim() || null,
        invoice_date: invoiceDate || null,
        notes: notes.trim() || null,
        items: lines.map((l) => ({
          product_id: l.product.id,
          quantity: l.quantity.trim(),
          unit_cost: l.unit_cost.trim(),
          batch_number: l.batch_number?.trim() || null,
          expiry_date: l.expiry_date || null,
        })),
      });
      // Everything a delivery changes: the order's progress, stock, costs and history.
      for (const key of ['purchase-order', 'purchase-orders', 'purchases', 'products', 'product', 'stock-summary', 'movements']) {
        void qc.invalidateQueries({ queryKey: [key] });
      }
      toast.success(`${grn.grn_number} recorded`, 'Stock and average costs are updated.');
      if (grn.price_changes.length) {
        toast.info(`${grn.price_changes.length} supplier price change(s)`, grn.price_changes.map((c) => `${c.product_name}: ${Number(c.change_percent) > 0 ? '+' : ''}${c.change_percent}%`).join(', '));
      }
      navigate(`/purchasing/receipts/${grn.id}`);
    } catch (err) {
      const p = parseError(err);
      setError(p.code === 'DUPLICATE_INVOICE' ? `${p.message} Check you are not entering it twice.` : errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <Link to={poId ? `/purchasing/orders/${poId}` : '/purchasing/receipts'} className="mb-4 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-800">
        <ArrowLeft className="h-4 w-4" /> {poId ? po.data?.po_number : 'Goods received'}
      </Link>
      <PageHeader title="Receive goods" description={poId ? `Against ${po.data?.po_number}. Adjust quantities to what actually arrived.` : 'Record a delivery from a supplier.'} />
      <div className="space-y-4">
        <Card>
          <div className="grid gap-4 sm:grid-cols-3">
            <Select label="Supplier" required placeholder="Choose a supplier" value={supplierId} disabled={poId !== null} onChange={(e) => setSupplierId(e.target.value)}
              options={(suppliers.data ?? []).map((s) => ({ value: String(s.id), label: s.name }))} />
            <Input label="Supplier invoice number" value={invoice} onChange={(e) => setInvoice(e.target.value)} hint="Prevents the same invoice being entered twice" />
            <Input label="Invoice date" type="date" value={invoiceDate} onChange={(e) => setInvoiceDate(e.target.value)} />
          </div>
        </Card>
        <Card title="What arrived" description="Unit costs exclude VAT. Perishables need their expiry date.">
          <LinesEditor lines={lines} onChange={setLines} withBatches />
        </Card>
        <Card><Textarea label="Notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. 2 cartons short, driver signed" /></Card>
        {error && <Alert tone="error">{error}</Alert>}
        {lines.length > 0 && problems.length > 0 && <Alert tone="warning">{problems[0]}</Alert>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => navigate(-1)}>Cancel</Button>
          <Button onClick={save} loading={saving} disabled={!supplierId || lines.length === 0 || problems.length > 0}>Receive into stock</Button>
        </div>
      </div>
    </>
  );
}

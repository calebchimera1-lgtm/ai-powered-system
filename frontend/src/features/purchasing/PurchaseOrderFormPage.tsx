import { useQuery } from '@tanstack/react-query';
import { ArrowLeft } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { purchasingApi } from '@/api/purchasing';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { Input, Select, Textarea } from '@/components/ui/Field';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { useSupplierOptions } from '@/features/products/hooks';
import { errorMessage } from '@/lib/errors';

import { type EditLine, LinesEditor, lineProblems } from './LinesEditor';

export function PurchaseOrderFormPage() {
  const params = useParams();
  const editId = params.id ? Number(params.id) : null;
  const navigate = useNavigate();
  const toast = useToast();
  const suppliers = useSupplierOptions();
  const existing = useQuery({ queryKey: ['purchase-order', editId], queryFn: () => purchasingApi.order(editId!), enabled: editId !== null });
  const [supplierId, setSupplierId] = useState('');
  const [expected, setExpected] = useState('');
  const [notes, setNotes] = useState('');
  const [lines, setLines] = useState<EditLine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const po = existing.data;
    if (!po || loaded) return;
    setSupplierId(String(po.supplier.id));
    setExpected(po.expected_date ?? '');
    setNotes(po.notes ?? '');
    setLines(po.items.map((i) => ({ product: i.product, quantity: String(Number(i.quantity_ordered)), unit_cost: String(Number(i.unit_cost)) })));
    setLoaded(true);
  }, [existing.data, loaded]);

  if (editId && existing.isLoading) return <div className="flex justify-center py-20"><Spinner label="Loading…" /></div>;
  const problems = lineProblems(lines, false);

  const save = async () => {
    setError(null);
    setSaving(true);
    const body = {
      supplier_id: Number(supplierId),
      expected_date: expected || null,
      notes: notes.trim() || null,
      items: lines.map((l) => ({ product_id: l.product.id, quantity: l.quantity.trim(), unit_cost: l.unit_cost.trim() })),
    };
    try {
      const po = editId ? await purchasingApi.updateOrder(editId, body) : await purchasingApi.createOrder(body);
      toast.success(editId ? 'Order saved' : `Order ${po.po_number} created`);
      navigate(`/purchasing/orders/${po.id}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <Link to="/purchasing/orders" className="mb-2.5 inline-flex items-center gap-1 py-1.5 text-sm text-gray-500 hover:text-gray-800"><ArrowLeft className="h-4 w-4" /> Purchase orders</Link>
      <PageHeader title={editId ? `Edit ${existing.data?.po_number}` : 'New purchase order'} description="Costs are what the supplier charges, excluding VAT." />
      <div className="space-y-4">
        <Card>
          <div className="grid gap-4 sm:grid-cols-2">
            <Select label="Supplier" required placeholder="Choose a supplier" value={supplierId} onChange={(e) => setSupplierId(e.target.value)}
              options={(suppliers.data ?? []).map((s) => ({ value: String(s.id), label: s.name }))} />
            <Input label="Expected delivery" type="date" value={expected} onChange={(e) => setExpected(e.target.value)} />
          </div>
          <div className="mt-4"><Textarea label="Notes for the supplier" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
        </Card>
        <Card title="Products">
          <LinesEditor lines={lines} onChange={setLines} />
        </Card>
        {error && <Alert tone="error">{error}</Alert>}
        {lines.length > 0 && problems.length > 0 && <Alert tone="warning">{problems[0]}</Alert>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => navigate(-1)}>Cancel</Button>
          <Button onClick={save} loading={saving} disabled={!supplierId || lines.length === 0 || problems.length > 0}>{editId ? 'Save order' : 'Create order'}</Button>
        </div>
      </div>
    </>
  );
}

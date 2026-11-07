import { useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { AlertTriangle, ArrowLeft, Check, CheckCircle2, Plus, RefreshCw, Trash2, XCircle, ZoomIn, ZoomOut } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { invoicesApi, type Invoice, type InvoiceFlag } from '@/api/invoices';
import type { Product } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { Input, Select, Textarea } from '@/components/ui/Field';
import { Modal } from '@/components/ui/Modal';
import { ProductPicker } from '@/components/ui/ProductPicker';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { useSupplierOptions } from '@/features/products/hooks';
import { errorMessage } from '@/lib/errors';
import { formatDateTime, formatKES } from '@/lib/format';

import {
  LOW_CONFIDENCE, MATCH_LABEL, STATUS_LABEL, STATUS_TONE, approvalProblems, blankLine, costExclVat,
  draftFrom, isWorking, lineAmount, toReviewInput, totalsCheck, type Draft, type DraftLine,
} from './review';

export function InvoiceReviewPage() {
  const id = Number(useParams().id);
  const query = useQuery({
    queryKey: ['invoice', id],
    queryFn: () => invoicesApi.get(id),
    refetchInterval: (q) => (q.state.data && isWorking(q.state.data.status) ? 1500 : false),
  });
  if (query.isLoading) return <div className="flex justify-center py-20"><Spinner label="Loading…" /></div>;
  if (query.isError || !query.data) return <Alert tone="error">{errorMessage(query.error)}</Alert>;
  const inv = query.data;
  return (
    <>
      <PageHeader
        title={inv.invoice_number ? `Invoice ${inv.invoice_number}` : 'Scanned invoice'}
        description={`${inv.original_filename} · uploaded ${formatDateTime(inv.created_at)} by ${inv.uploaded_by.full_name}`}
        actions={<Link to="/purchasing/invoices" className="inline-flex items-center gap-1 text-sm font-medium text-gray-600 hover:text-gray-900"><ArrowLeft className="h-4 w-4" />All invoices</Link>}
      />
      {isWorking(inv.status) ? (
        <Card>
          <div className="flex flex-col items-center gap-3 py-12 text-center">
            <Spinner label="" />
            <p className="font-medium text-gray-900">{STATUS_LABEL[inv.status]}</p>
            <p className="max-w-sm text-sm text-gray-500">Straightening the photo, reading the text and matching products. This usually takes a few seconds.</p>
          </div>
        </Card>
      ) : (
        // Keyed by id + status so a finished read or an approval starts from the server's copy.
        <Review key={`${inv.id}-${inv.status}`} inv={inv} />
      )}
    </>
  );
}

function DocumentImage({ inv }: { inv: Invoice }) {
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(false);
  const blob = useQuery({
    queryKey: ['invoice', inv.id, 'page', page],
    queryFn: () => invoicesApi.pageBlob(inv.id, page),
    staleTime: Infinity,
    retry: false,
  });
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!blob.data) return;
    const u = URL.createObjectURL(blob.data);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [blob.data]);

  return (
    <Card title="Document" bodyClassName="p-0"
      actions={
        <>
          {inv.page_count > 1 && Array.from({ length: inv.page_count }, (_, i) => (
            <Button key={i} size="sm" variant={page === i + 1 ? 'primary' : 'secondary'} onClick={() => setPage(i + 1)}>{i + 1}</Button>
          ))}
          <Button size="sm" variant="ghost" onClick={() => setZoom((z) => !z)} aria-label={zoom ? 'Fit to width' : 'Zoom in'} icon={zoom ? <ZoomOut className="h-4 w-4" /> : <ZoomIn className="h-4 w-4" />} />
        </>
      }>
      <div className={clsx('max-h-[75vh] overflow-auto bg-gray-100', zoom && 'cursor-zoom-out')}>
        {blob.isError ? (
          <p className="p-6 text-sm text-gray-500">The page image is not available.</p>
        ) : url ? (
          <img src={url} alt={`Page ${page} of the uploaded invoice, as straightened for reading`} onClick={() => setZoom((z) => !z)}
            className={clsx('mx-auto block', zoom ? 'max-w-none' : 'w-full cursor-zoom-in')} style={zoom ? { width: '200%' } : undefined} />
        ) : <div className="flex justify-center py-20"><Spinner label="Loading page…" /></div>}
      </div>
      {inv.processing_steps && (
        <p className="border-t border-gray-100 px-4 py-2 text-xs text-gray-500">
          Read with {inv.ocr_engine === 'pdf-text' ? 'the PDF text (no OCR needed)' : 'OCR'}
          {inv.processing_ms !== null && ` in ${(inv.processing_ms / 1000).toFixed(1)} s`}
          {inv.processing_steps.length > 0 && ` · ${inv.processing_steps.join('; ')}`}
        </p>
      )}
    </Card>
  );
}

function FlagList({ flags }: { flags: InvoiceFlag[] }) {
  if (flags.length === 0) return null;
  const blocking = flags.filter((f) => f.severity === 'error');
  return (
    <div className={clsx('rounded-xl border p-4', blocking.length ? 'border-red-200 bg-red-50' : 'border-amber-200 bg-amber-50')} role="status">
      <p className={clsx('flex items-center gap-2 text-sm font-semibold', blocking.length ? 'text-red-800' : 'text-amber-900')}>
        <AlertTriangle className="h-4 w-4" aria-hidden />
        {flags.length === 1 ? '1 thing to check' : `${flags.length} things to check`}
      </p>
      <ul className="mt-2 list-disc space-y-1 pl-6 text-sm text-gray-800">
        {flags.map((f, i) => <li key={i}>{f.message}</li>)}
      </ul>
    </div>
  );
}

function Review({ inv }: { inv: Invoice }) {
  const { can, canAny } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const suppliers = useSupplierOptions();
  const [draft, setDraft] = useState<Draft>(() => draftFrom(inv));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<null | 'save' | 'approve' | 'reject' | 'reprocess'>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectNote, setRejectNote] = useState('');

  const editable = (inv.status === 'NEEDS_REVIEW' || inv.status === 'FAILED') && canAny(PERM.INVOICES_UPLOAD, PERM.INVOICES_APPROVE);
  const canApprove = can(PERM.INVOICES_APPROVE);
  const conf = inv.field_confidences ?? {};
  const flags = inv.flags ?? [];
  const lineFlags = (i: number) => flags.filter((f) => f.item === i);
  const headerFlags = flags.filter((f) => f.item === null || f.item === undefined);

  const set = (patch: Partial<Draft>) => { setDraft((d) => ({ ...d, ...patch })); setDirty(true); };
  const setLine = (key: string, patch: Partial<DraftLine>) => {
    setDraft((d) => ({ ...d, lines: d.lines.map((l) => (l.key === key ? { ...l, ...patch } : l)) }));
    setDirty(true);
  };

  const refresh = (next: Invoice) => {
    qc.setQueryData(['invoice', inv.id], next);
    void qc.invalidateQueries({ queryKey: ['invoices'] });
  };

  const save = async (): Promise<Invoice | null> => {
    setError(null);
    try {
      const next = await invoicesApi.save(inv.id, toReviewInput(draft));
      setDirty(false);
      return next;
    } catch (e) {
      setError(errorMessage(e));
      return null;
    }
  };

  const onSave = async () => {
    setBusy('save');
    const next = await save();
    setBusy(null);
    if (next) {
      // Re-key from the saved copy (new line ids, refreshed checks).
      setDraft(draftFrom(next));
      qc.setQueryData(['invoice', inv.id], next);
      toast.success('Changes saved');
    }
  };

  const onApprove = async () => {
    setBusy('approve');
    const saved = await save();
    if (!saved) { setBusy(null); setConfirmOpen(false); return; }
    try {
      const done = await invoicesApi.approve(inv.id);
      toast.success('Invoice approved and goods received into stock');
      void qc.invalidateQueries({ queryKey: ['products'] });
      void qc.invalidateQueries({ queryKey: ['purchases'] });
      refresh(done);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (e) {
      qc.setQueryData(['invoice', inv.id], saved);
      setDraft(draftFrom(saved));
      setError(errorMessage(e));
    } finally {
      setBusy(null);
      setConfirmOpen(false);
    }
  };

  const onReject = async () => {
    setBusy('reject');
    try {
      refresh(await invoicesApi.reject(inv.id, rejectNote.trim()));
      window.scrollTo({ top: 0, behavior: 'smooth' });
      toast.success('Invoice rejected');
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
      setRejectOpen(false);
    }
  };

  const onReprocess = async () => {
    setBusy('reprocess');
    try {
      refresh(await invoicesApi.reprocess(inv.id));
    } catch (e) {
      setError(errorMessage(e));
      setBusy(null);
    }
  };

  // The server's warnings describe the line as last saved; once the reviewer edits it they
  // may no longer apply (the client-side checks below cover the edited values).
  const changedSinceRead = (l: DraftLine) => {
    const saved = inv.items.find((i) => i.id === l.id);
    return !saved || saved.product?.id !== l.product?.id || Number(saved.quantity) !== Number(l.quantity) || Number(saved.unit_price) !== Number(l.unit_price);
  };
  const problems = approvalProblems(draft);
  const check = totalsCheck(draft);
  const low = (field: string) => editable && conf[field] !== undefined && conf[field] < LOW_CONFIDENCE;
  const hint = (field: string) => (low(field) ? 'Not read clearly: check against the document' : undefined);
  const lowCls = (field: string) => (low(field) ? '!border-amber-400 !bg-amber-50' : undefined);
  const supplierOptions = (suppliers.data ?? []).map((s) => ({ value: String(s.id), label: s.name }));
  const receivedTotal = draft.lines.reduce((acc, l) => {
    const c = costExclVat(l, draft.prices_include_vat);
    const q = Number(l.quantity);
    return acc + (c !== null && q > 0 ? c * q : 0);
  }, 0);

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <div className="xl:sticky xl:top-4 xl:self-start">
        <DocumentImage inv={inv} />
      </div>

      <div className="min-w-0 space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={STATUS_TONE[inv.status]}>{STATUS_LABEL[inv.status]}</Badge>
          {inv.reviewed_by && <span className="text-sm text-gray-600">by {inv.reviewed_by.full_name}, {formatDateTime(inv.reviewed_at)}</span>}
          {inv.purchase_id && <Link className="text-sm font-medium text-brand-700 hover:underline" to={`/purchasing/receipts/${inv.purchase_id}`}>View goods-received note</Link>}
        </div>
        {inv.review_note && <Alert tone="info">Note: {inv.review_note}</Alert>}
        {inv.status === 'FAILED' && <Alert tone="error">The document could not be read{inv.error_message ? `: ${inv.error_message}` : '.'} You can type the details in by hand below, or reject it.</Alert>}
        {inv.quality && inv.quality.problems.length > 0 && editable && (
          <Alert tone="warning">{inv.quality.problems.join(' ')} If the values below look wrong, a clearer photo will read better.</Alert>
        )}
        {editable && <FlagList flags={headerFlags} />}
        {error && <Alert tone="error">{error}</Alert>}

        <Card title="Invoice details">
          <fieldset disabled={!editable} className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Select label="Supplier" required value={draft.supplier_id} onChange={(e) => set({ supplier_id: e.target.value })}
                options={supplierOptions} placeholder="Choose the supplier"
                hint={inv.extracted_supplier_name ? `Printed: ${inv.extracted_supplier_name}${inv.kra_pin ? ` · PIN ${inv.kra_pin}` : ''}` : hint('supplier')}
                className={lowCls('supplier')} />
            </div>
            <Input label="Invoice number" required value={draft.invoice_number} onChange={(e) => set({ invoice_number: e.target.value })} hint={hint('invoice_number')} className={lowCls('invoice_number')} />
            <Input label="Invoice date" type="date" value={draft.invoice_date} onChange={(e) => set({ invoice_date: e.target.value })} hint={hint('invoice_date')} className={lowCls('invoice_date')} />
            <Input label="Subtotal (KES)" inputMode="decimal" value={draft.subtotal} onChange={(e) => set({ subtotal: e.target.value })} hint={hint('subtotal')} className={lowCls('subtotal')} />
            <Input label="VAT (KES)" inputMode="decimal" value={draft.tax_total} onChange={(e) => set({ tax_total: e.target.value })} hint={hint('tax_total')} className={lowCls('tax_total')} />
            <Input label="Total (KES)" inputMode="decimal" value={draft.grand_total} onChange={(e) => set({ grand_total: e.target.value })} hint={hint('grand_total')} className={lowCls('grand_total')} />
            <label className="flex items-start gap-2 self-end pb-2 text-sm text-gray-700">
              <input type="checkbox" className="mt-0.5 h-4 w-4 rounded border-gray-300 text-brand-600" checked={draft.prices_include_vat} onChange={(e) => set({ prices_include_vat: e.target.checked })} />
              <span>Line prices include VAT<span className="block text-xs text-gray-500">Stock costs are recorded without VAT.</span></span>
            </label>
          </fieldset>
        </Card>

        <Card title={`Lines (${draft.lines.length})`} description={editable ? 'Each line needs a product from your catalogue. Fix any number that does not match the document.' : undefined}
          actions={editable && <Button size="sm" variant="secondary" icon={<Plus className="h-4 w-4" />} onClick={() => set({ lines: [...draft.lines, blankLine()] })}>Add line</Button>}
          bodyClassName="p-0">
          {draft.lines.length === 0 && <p className="p-5 text-sm text-gray-500">No lines were read. Add them by hand.</p>}
          <ol className="divide-y divide-gray-100">
            {draft.lines.map((l, idx) => (
              <LineRow key={l.key} line={l} index={idx} editable={editable} pricesIncludeVat={draft.prices_include_vat}
                flags={l.id !== null && !changedSinceRead(l) ? lineFlags(idx) : []} onChange={(p) => setLine(l.key, p)}
                onRemove={() => set({ lines: draft.lines.filter((x) => x.key !== l.key) })} />
            ))}
          </ol>
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-gray-100 px-4 py-3 text-sm sm:px-5">
            <span className="text-gray-600">Lines add up to <strong className="tabular-nums text-gray-900">{formatKES(check.sum)}</strong></span>
            {check.matches === true && <span className="inline-flex items-center gap-1 text-brand-700"><CheckCircle2 className="h-4 w-4" />Matches the {check.expectedLabel.toLowerCase()}</span>}
            {check.matches === false && <span className="inline-flex items-center gap-1 text-amber-700"><AlertTriangle className="h-4 w-4" />{check.expectedLabel} on the invoice is {formatKES(check.expected)}</span>}
          </div>
        </Card>

        {editable && (
          <div className="sticky bottom-0 z-10 -mx-4 border-t border-gray-200 bg-white/95 px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-xl sm:border">
            {problems.length > 0 && canApprove && (
              <p className="mb-2 text-xs text-gray-600"><span className="font-medium">Before approving:</span> {problems.slice(0, 3).join(' ')}{problems.length > 3 && ` (+${problems.length - 3} more)`}</p>
            )}
            <div className="flex flex-wrap items-center gap-2">
              {canApprove && <Button icon={<Check className="h-4 w-4" />} disabled={problems.length > 0 || busy !== null} onClick={() => setConfirmOpen(true)}>Approve and receive</Button>}
              <Button variant="secondary" onClick={onSave} loading={busy === 'save'} disabled={!dirty || busy !== null}>Save changes</Button>
              <div className="ml-auto flex gap-2">
                {can(PERM.INVOICES_UPLOAD) && <Button variant="ghost" size="sm" icon={<RefreshCw className="h-4 w-4" />} onClick={onReprocess} loading={busy === 'reprocess'} disabled={busy !== null}
                  title="Read the document again, e.g. after adding the supplier or a product">Read again</Button>}
                {canApprove && <Button variant="ghost" size="sm" icon={<XCircle className="h-4 w-4" />} onClick={() => setRejectOpen(true)} disabled={busy !== null}>Reject</Button>}
              </div>
            </div>
          </div>
        )}
      </div>

      {confirmOpen && (
        <Modal open onClose={() => setConfirmOpen(false)} title="Receive this delivery into stock?" busy={busy === 'approve'}
          footer={<><Button variant="secondary" onClick={() => setConfirmOpen(false)} disabled={busy === 'approve'}>Cancel</Button><Button onClick={onApprove} loading={busy === 'approve'}>Approve and receive</Button></>}>
          <div className="space-y-3 text-sm text-gray-700">
            <p>{draft.lines.length} {draft.lines.length === 1 ? 'line' : 'lines'} from <strong>{supplierOptions.find((s) => s.value === draft.supplier_id)?.label}</strong>, invoice <strong>{draft.invoice_number}</strong>, will be added to stock at a cost of <strong className="tabular-nums">{formatKES(receivedTotal)}</strong> before VAT.</p>
            <p>Average costs and supplier prices update, and a goods-received note is created. This cannot be undone from here; mistakes are corrected with a stock adjustment.</p>
          </div>
        </Modal>
      )}
      {rejectOpen && (
        <Modal open onClose={() => setRejectOpen(false)} title="Reject this invoice?" busy={busy === 'reject'}
          footer={<><Button variant="secondary" onClick={() => setRejectOpen(false)}>Cancel</Button><Button variant="danger" onClick={onReject} loading={busy === 'reject'} disabled={!rejectNote.trim()}>Reject</Button></>}>
          <Textarea label="Reason" required value={rejectNote} onChange={(e) => setRejectNote(e.target.value)} placeholder="e.g. Duplicate of an invoice already received; not our delivery" maxLength={500} rows={3} />
        </Modal>
      )}
    </div>
  );
}

function LineRow({ line: l, index, editable, pricesIncludeVat, flags, onChange, onRemove }: {
  line: DraftLine; index: number; editable: boolean; pricesIncludeVat: boolean; flags: InvoiceFlag[];
  onChange: (p: Partial<DraftLine>) => void; onRemove: () => void;
}) {
  const [changing, setChanging] = useState(false);
  const amount = lineAmount(l);
  const printed = l.line_total.trim() === '' ? null : Number(l.line_total);
  const mismatch = amount !== null && printed !== null && Math.abs(amount - printed) > 1;
  const cost = costExclVat(l, pricesIncludeVat);
  const lowConf = editable && l.id !== null && l.confidence < LOW_CONFIDENCE && l.match_method !== 'MANUAL';
  const pick = (p: Product) => {
    onChange({ product: { id: p.id, name: p.name, sku: p.sku, unit_of_measure: p.unit_of_measure, tracks_expiry: p.tracks_expiry, vat_rate: p.vat_rate, purchase_price: p.purchase_price ?? null }, suggested: false, match_method: 'MANUAL' });
    setChanging(false);
  };
  const lineNo = index + 1;

  return (
    <li className={clsx('px-4 py-4 sm:px-5', (l.suggested || !l.product) && editable && 'bg-amber-50/40')}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Line {lineNo}{l.item_code && ` · code ${l.item_code}`}</p>
          {editable ? (
            <input aria-label={`Line ${lineNo} description as printed`} value={l.description} onChange={(e) => onChange({ description: e.target.value })}
              className="mt-0.5 w-full rounded border border-transparent bg-transparent px-1 py-0.5 font-mono text-sm text-gray-900 hover:border-gray-200 focus:border-brand-500 focus:outline-none" placeholder="Description as printed" />
          ) : <p className="mt-0.5 font-mono text-sm text-gray-900">{l.description}</p>}
        </div>
        {editable && <Button variant="ghost" size="sm" onClick={onRemove} aria-label={`Remove line ${lineNo}`} icon={<Trash2 className="h-4 w-4" />} />}
      </div>

      {/* Product */}
      <div className="mt-2">
        {l.product && !changing ? (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium text-gray-900">{l.product.name}</span>
            <span className="text-xs text-gray-500">{l.product.sku}</span>
            {l.suggested ? (
              <Badge tone="amber">Suggested{l.match_score !== null && ` (${Math.round(l.match_score)}%)`}</Badge>
            ) : <Badge tone={l.match_method === 'MANUAL' ? 'blue' : 'green'}>{MATCH_LABEL[l.match_method] ?? l.match_method}</Badge>}
            {editable && l.suggested && <Button size="sm" icon={<Check className="h-4 w-4" />} onClick={() => onChange({ suggested: false })}>Confirm</Button>}
            {editable && <Button size="sm" variant="ghost" onClick={() => setChanging(true)}>Change</Button>}
          </div>
        ) : editable ? (
          <div className="max-w-md">
            <ProductPicker label={`Product for line ${lineNo}`} placeholder="Search the catalogue for this product" showPrice={false} onPick={pick} autoFocus={changing} />
            {changing && <button type="button" className="mt-1 text-xs text-gray-500 hover:underline" onClick={() => setChanging(false)}>Keep {l.product?.name}</button>}
          </div>
        ) : <span className="text-sm text-gray-500">No product</span>}
      </div>

      {/* Numbers */}
      <fieldset disabled={!editable} className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <NumberField label="Quantity" name={`Line ${lineNo} quantity`} value={l.quantity} onChange={(v) => onChange({ quantity: v })} flagged={lowConf} suffix={l.product?.unit_of_measure} />
        <NumberField label={pricesIncludeVat ? 'Unit price (incl. VAT)' : 'Unit price'} name={`Line ${lineNo} unit price`} value={l.unit_price} onChange={(v) => onChange({ unit_price: v })} flagged={lowConf} />
        <NumberField label="Line total" name={`Line ${lineNo} total`} value={l.line_total} onChange={(v) => onChange({ line_total: v })} flagged={mismatch} />
        {l.product?.tracks_expiry ? (
          <label className="text-xs font-medium text-gray-600">Expiry date<span className="text-red-600">*</span>
            <input type="date" aria-label={`Line ${lineNo} expiry date`} value={l.expiry_date} onChange={(e) => onChange({ expiry_date: e.target.value })} className="mt-1 h-9 w-full rounded-lg border border-gray-300 px-2 text-sm" />
          </label>
        ) : (
          <div className="text-xs text-gray-600">
            <span className="font-medium">Stock cost / unit</span>
            <p className="mt-2 tabular-nums text-sm text-gray-900">{cost !== null ? formatKES(cost) : '—'}<span className="text-xs text-gray-500"> excl. VAT</span></p>
          </div>
        )}
      </fieldset>
      {mismatch && <p className="mt-2 text-xs text-amber-700">{l.quantity} × {l.unit_price} = {formatKES(amount)}, but the line total says {formatKES(printed)}. Check the numbers against the document.</p>}
      {editable && flags.filter((f) => f.code !== 'LINE_ARITHMETIC').map((f, i) => <p key={i} className="mt-1 text-xs text-amber-700">{f.message}</p>)}
      {l.raw_text && <p className="mt-2 truncate font-mono text-[11px] text-gray-400" title={l.raw_text}>Read as: {l.raw_text}</p>}
    </li>
  );
}

function NumberField({ label, name, value, onChange, flagged, suffix }: { label: string; name: string; value: string; onChange: (v: string) => void; flagged?: boolean; suffix?: string }) {
  return (
    <label className="text-xs font-medium text-gray-600">
      {label}
      <span className="relative mt-1 block">
        <input inputMode="decimal" aria-label={name} value={value} onChange={(e) => onChange(e.target.value.replace(/[^\d.]/g, ''))}
          className={clsx('h-9 w-full rounded-lg border px-2 text-right text-sm tabular-nums focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30 disabled:bg-gray-50',
            flagged ? 'border-amber-400 bg-amber-50' : 'border-gray-300', suffix && 'pr-10')} />
        {suffix && <span aria-hidden className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[11px] text-gray-400">{suffix}</span>}
      </span>
    </label>
  );
}

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft } from 'lucide-react';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { anomaliesApi, type AlertStatus, type AnomalyAlert } from '@/api/analytics';
import { useAuth } from '@/auth/AuthProvider';
import { PERM } from '@/auth/permissions';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Card';
import { Textarea } from '@/components/ui/Field';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { errorMessage, parseError } from '@/lib/errors';
import { formatDateTime, formatKES } from '@/lib/format';

import { DETECTOR_LABEL, FIGURE_LABEL, SEVERITY_LABEL, SEVERITY_TONE, STATUS_LABEL, STATUS_TONE, period, subject } from './labels';

const fmt = (n: number) => n.toLocaleString('en-KE', { maximumFractionDigits: 1 });
const dm = (iso: string) => new Intl.DateTimeFormat('en-KE', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(`${iso}T00:00:00Z`));

export function AnomalyDetailPage() {
  const id = Number(useParams().id);
  const q = useQuery({ queryKey: ['anomaly', id], queryFn: () => anomaliesApi.get(id) });
  if (q.isLoading) return <div className="flex justify-center py-20"><Spinner label="Loading…" /></div>;
  if (q.isError || !q.data) return <Alert tone="error">{errorMessage(q.error)}</Alert>;
  const a = q.data;
  return (
    <>
      <PageHeader title={a.kind_label} description={`${subject(a)} · ${period(a)}`}
        actions={<Link to="/anomalies" className="inline-flex items-center gap-1 py-1.5 text-sm font-medium text-gray-600 hover:text-gray-900"><ArrowLeft className="h-4 w-4" />All irregularities</Link>} />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={SEVERITY_TONE[a.severity]}>{SEVERITY_LABEL[a.severity]} severity</Badge>
              <Badge tone={STATUS_TONE[a.status]}>{STATUS_LABEL[a.status]}</Badge>
              <span className="text-xs text-gray-500">Found by: {DETECTOR_LABEL[a.detector]} · {formatDateTime(a.detected_at)}</span>
            </div>
            <p className="mt-3 text-gray-900">{a.explanation}</p>
            {Number(a.value_kes) > 0 && <p className="mt-2 text-sm text-gray-600">Value involved: <strong className="tabular-nums text-gray-900">{formatKES(a.value_kes)}</strong></p>}
            <div className="mt-4 rounded-lg bg-gray-50 p-3 text-sm text-gray-800">
              <p className="font-medium text-gray-900">Suggested check</p>
              <p className="mt-1">{a.recommended_action}</p>
            </div>
            {a.entity_type === 'product' && a.product && (
              <p className="mt-3 text-sm"><Link to={`/stock/movements?product=${a.product.id}`} className="font-medium text-brand-700 hover:underline">See this product's stock movements</Link></p>
            )}
          </Card>
          <Evidence alert={a} />
        </div>
        <Review alert={a} />
      </div>
    </>
  );
}

function Evidence({ alert }: { alert: AnomalyAlert }) {
  return (
    <Card title="What was unusual" description="Each figure against the normal for the same product or person over the previous 90 days (median)." bodyClassName="p-0">
      {(alert.evidence ?? []).map((e) => (
        <div key={e.day} className="border-t border-gray-100 first:border-t-0">
          <p className="bg-gray-50 px-4 py-2 text-xs font-medium uppercase tracking-wide text-gray-500">{dm(e.day)}</p>
          <table className="min-w-full text-sm">
            <thead className="sr-only"><tr><th>Figure</th><th>That day</th><th>Normal</th></tr></thead>
            <tbody className="divide-y divide-gray-100">
              {Object.entries(e.figures).map(([k, v]) => (
                <tr key={k}>
                  <td className="px-4 py-2 text-gray-700">{FIGURE_LABEL[k] ?? k}</td>
                  <td className="px-3 py-2 text-right font-medium tabular-nums text-gray-900">{fmt(v.value)}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-gray-500">normal {fmt(v.normal)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </Card>
  );
}

const OPTIONS: { value: AlertStatus; label: string; hint: string }[] = [
  { value: 'INVESTIGATING', label: 'Investigating', hint: 'Being looked into' },
  { value: 'RESOLVED_ISSUE_FOUND', label: 'Issue found', hint: 'A real loss or mistake was confirmed' },
  { value: 'RESOLVED_NO_ISSUE', label: 'No issue', hint: 'There was a good explanation' },
];

function Review({ alert }: { alert: AnomalyAlert }) {
  const { can, user } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [status, setStatus] = useState<AlertStatus>(alert.status === 'OPEN' ? 'INVESTIGATING' : alert.status);
  const [notes, setNotes] = useState(alert.review_notes ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const own = alert.entity_type === 'user' && alert.subject_user?.id === user?.id;
  const needsNote = status.startsWith('RESOLVED') && !notes.trim();

  if (!can(PERM.ANOMALIES_REVIEW)) {
    return <Card title="Review">{alert.reviewed_by ? <p className="text-sm text-gray-700">{STATUS_LABEL[alert.status]} by {alert.reviewed_by.full_name}. {alert.review_notes}</p> : <p className="text-sm text-gray-600">A manager reviews irregularities.</p>}</Card>;
  }
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await anomaliesApi.review(alert.id, status, notes.trim());
      qc.setQueryData(['anomaly', alert.id], next);
      void qc.invalidateQueries({ queryKey: ['anomalies'] });
      toast.success('Review saved');
    } catch (e) {
      setError(parseError(e).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Review" description={alert.reviewed_by ? `Last updated by ${alert.reviewed_by.full_name}, ${formatDateTime(alert.reviewed_at)}` : 'Record what you found. This also measures how useful these alerts are.'}>
      {own ? (
        <Alert tone="info">This alert is about your own activity, so another manager must review it.</Alert>
      ) : (
        <div className="space-y-4">
          <fieldset>
            <legend className="mb-2 text-sm font-medium text-gray-700">Outcome</legend>
            <div className="space-y-2">
              {OPTIONS.map((o) => (
                <label key={o.value} className="flex cursor-pointer items-start gap-2 rounded-lg border border-gray-200 p-2.5 has-[:checked]:border-brand-500 has-[:checked]:bg-brand-50/50">
                  <input type="radio" name="outcome" value={o.value} checked={status === o.value} onChange={() => setStatus(o.value)} className="mt-0.5 h-4 w-4 text-brand-600" />
                  <span className="text-sm"><span className="font-medium text-gray-900">{o.label}</span><span className="block text-xs text-gray-500">{o.hint}</span></span>
                </label>
              ))}
            </div>
          </fieldset>
          <Textarea label="Notes" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={2000}
            placeholder="e.g. Recounted: 9 bags missing from the store room; shift supervisor informed"
            hint={status.startsWith('RESOLVED') ? 'Required when resolving' : undefined} />
          {error && <Alert tone="error">{error}</Alert>}
          <Button onClick={save} loading={busy} disabled={needsNote}>Save review</Button>
        </div>
      )}
    </Card>
  );
}

import { Check, Copy } from 'lucide-react';
import { useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { formatDateTime } from '@/lib/format';

/** Shows a one-time setup/reset link that the admin passes to the staff member. */
export function LinkModal({
  link,
  onClose,
}: {
  link: { title: string; name: string; url: string; expiresAt: string } | null;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  if (!link) return null;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link.url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard can be blocked on plain-HTTP origins; the field is selectable instead.
    }
  };

  return (
    <Modal
      open
      onClose={() => {
        setCopied(false);
        onClose();
      }}
      title={link.title}
      footer={<Button onClick={onClose}>Done</Button>}
    >
      <div className="space-y-4">
        <p className="text-sm text-gray-600">
          Give this link to <span className="font-medium text-gray-900">{link.name}</span>. It works once and expires{' '}
          {formatDateTime(link.expiresAt)}.
        </p>
        <div className="flex gap-2">
          <input
            readOnly
            value={link.url}
            aria-label="Password link"
            onFocus={(e) => e.currentTarget.select()}
            className="h-10 min-w-0 flex-1 rounded-lg border border-gray-300 bg-gray-50 px-3 font-mono text-xs text-gray-700"
          />
          <Button
            variant="secondary"
            onClick={copy}
            icon={copied ? <Check className="h-4 w-4 text-brand-600" /> : <Copy className="h-4 w-4" />}
          >
            {copied ? 'Copied' : 'Copy'}
          </Button>
        </div>
        <Alert tone="warning">Treat this like a password: share it only with this person.</Alert>
      </div>
    </Modal>
  );
}

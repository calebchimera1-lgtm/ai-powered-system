import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Boxes } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { api } from '@/api/client';
import type { LegalInfo } from '@/api/types';
import { AppFooter } from '@/components/layout/AppFooter';
import { usePageTitle } from '@/hooks/usePageTitle';

const UPDATED = '27 November 2026';

function useLegal() {
  return useQuery({
    queryKey: ['legal'],
    queryFn: () => api.get<LegalInfo>('/legal').then((r) => r.data),
    staleTime: 10 * 60_000,
    retry: false,
  });
}

function LegalLayout({ title, children }: { title: string; children: ReactNode }) {
  usePageTitle(title);
  return (
    <div className="min-h-screen bg-gray-50 px-4 py-8">
      <div className="mx-auto max-w-3xl">
        <div className="mb-6 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-600 text-white"><Boxes className="h-5 w-5" aria-hidden /></div>
            <p className="font-semibold text-gray-900">Smart Inventory</p>
          </div>
          <Link to="/" className="inline-flex items-center gap-1 py-2 text-sm font-medium text-gray-600 hover:text-gray-900"><ArrowLeft className="h-4 w-4" />Back</Link>
        </div>
        <article className="rounded-2xl border border-gray-200 bg-white p-6 text-sm leading-relaxed text-gray-700 shadow-card sm:p-8 [&_h2]:mt-6 [&_h2]:text-base [&_h2]:font-semibold [&_h2]:text-gray-900 [&_li]:mt-1 [&_p]:mt-2 [&_ul]:mt-2 [&_ul]:list-disc [&_ul]:pl-5">
          <h1 className="text-xl font-semibold text-gray-900 sm:text-2xl">{title}</h1>
          <p className="text-xs text-gray-500">Last updated {UPDATED}</p>
          {children}
        </article>
        <AppFooter signedIn={false} className="mt-8" />
      </div>
    </div>
  );
}

function Shop({ info }: { info: LegalInfo | undefined }) {
  if (!info) return <>the shop that runs this system</>;
  return (
    <>
      <strong>{info.store_name}</strong>, {info.store_address}
      {info.store_kra_pin && <> (KRA PIN {info.store_kra_pin})</>}
    </>
  );
}

export function PrivacyPage() {
  const { data: info } = useLegal();
  const contact = info?.privacy_contact || info?.store_phone || 'the store manager';
  return (
    <LegalLayout title="Privacy notice">
      <p>
        This notice explains what personal data the Smart Inventory system at <Shop info={info} /> holds,
        why, who it is shared with and your rights under the Kenya Data Protection Act, 2019. The shop is the
        data controller. Questions and requests: <strong>{contact}</strong>.
      </p>

      <h2>Whose data, and what</h2>
      <ul>
        <li><strong>Staff:</strong> name, username, e-mail, phone, role, password (stored only as an Argon2 hash, never readable), optional two-step sign-in secret, sign-in sessions with IP address and device name, and a record of the actions each person takes (the audit log).</li>
        <li><strong>Customers:</strong> nothing is required to buy. A customer name or phone number is kept only if given at the till (for example for a receipt or a return). For an M-Pesa payment prompt, the phone number, amount and M-Pesa receipt number are kept with the sale.</li>
        <li><strong>Suppliers:</strong> business contact details and the invoices they send, which may name their staff.</li>
        {info?.ai_assistant && <li><strong>AI assistant:</strong> the questions staff ask, files they attach (receipts, invoices), the answers and what the assistant looked up.</li>}
      </ul>

      <h2>Why (purpose and lawful basis)</h2>
      <ul>
        <li>To run the shop: selling, stock, purchasing, payments and returns (contract and legitimate interest).</li>
        <li>To keep accounts and tax records the law requires, such as sales, VAT and supplier invoices (legal obligation).</li>
        <li>To keep the system secure and find mistakes or theft: sign-in records and the audit log (legitimate interest).</li>
      </ul>
      <p>Personal data is <strong>not</strong> sold, and it is not used for marketing or advertising. The system sends no marketing messages and uses no tracking or advertising cookies.</p>

      <h2>Who it is shared with</h2>
      <ul>
        <li>Staff of the shop, each seeing only what their role needs.</li>
        {info?.mpesa_prompts && <li><strong>Safaricom</strong> (M-Pesa), to send a payment prompt: the phone number and amount.</li>}
        {info?.ai_assistant && <li><strong>Anthropic</strong> (the Claude AI service, United States), to answer AI assistant questions and read scanned invoices: the question, attached file and the figures needed for the answer. This is a transfer outside Kenya; it is used only when the shop has switched the AI features on.</li>}
        {info?.document_archive && <li>The shop’s document archive, which runs on the shop’s own server.</li>}
        <li>Authorities such as the Kenya Revenue Authority, when the law requires it.</li>
      </ul>

      <h2>How long it is kept</h2>
      <ul>
        <li>Sales, purchases, invoices and accounting records: as long as tax law requires (in Kenya generally at least five years), then they may be deleted.</li>
        <li>Staff accounts: while the person works for the shop. Afterwards the account is deactivated and, on request, the personal details are erased; the records they made stay, linked to “Former staff member”.</li>
        <li>Sign-in sessions: until they expire or the person signs out. Backups: rotated automatically.</li>
      </ul>

      <h2>Cookies and storage in your browser</h2>
      <p>
        One cookie is used: a sign-in cookie that keeps you signed in. It is strictly necessary, cannot be read by
        page scripts (HttpOnly) and is sent only to this system. There are no analytics, advertising or third-party
        cookies, so no cookie consent banner is needed.
      </p>

      <h2>Security</h2>
      <p>
        Passwords are hashed, access depends on each person’s role, every important action is logged, data is backed
        up every night, and secrets such as database passwords and API keys stay on the server. If personal data is
        ever exposed, the shop follows its breach plan and informs the Data Protection Commissioner and the people
        affected as the law requires.
      </p>

      <h2>Your rights</h2>
      <p>
        You may ask to see the personal data held about you, have it corrected, object to its use, have it deleted
        where the law allows, or receive a copy. Ask using the contact above. If you are not satisfied, you may complain
        to the Office of the Data Protection Commissioner (odpc.go.ke).
      </p>
      <p className="text-xs text-gray-500">This notice describes how this software works. The shop should have it checked against its own practices before relying on it.</p>
    </LegalLayout>
  );
}

export function TermsPage() {
  const { data: info } = useLegal();
  return (
    <LegalLayout title="Terms of use">
      <p>
        Smart Inventory is the internal management system of <Shop info={info} />. It is for the shop’s staff only.
        By signing in you agree to these terms.
      </p>

      <h2>Accounts</h2>
      <ul>
        <li>Accounts are created by the shop’s administrator; there is no public sign-up. Staff accounts are for people employed by the shop.</li>
        <li>Keep your password private and do not let anyone else use your account. Everything done with your account is recorded in your name.</li>
        <li>Sign out on shared computers. Tell a manager at once if you think someone else knows your password.</li>
      </ul>

      <h2>Acceptable use</h2>
      <ul>
        <li>Use the system only for your work at the shop, and only enter information that is true.</li>
        <li>Do not try to see information your role does not allow, change records to hide mistakes or losses, or copy customer or business data out of the system without permission.</li>
        <li>Personal data of customers and colleagues must be handled as described in the <Link to="/privacy" className="font-medium text-brand-700 underline">privacy notice</Link>.</li>
      </ul>

      {info?.ai_assistant && (
        <>
          <h2>AI features</h2>
          <p>
            The AI assistant and AI invoice reading can make mistakes. Answers come from the shop’s records, but always
            check figures, and check every scanned invoice against the paper before you approve it. The assistant never
            saves anything itself: a person must confirm each entry and is responsible for it.
          </p>
        </>
      )}

      <h2>Customers</h2>
      <p>
        Prices shown at the till include VAT. {info?.mpesa_prompts && 'M-Pesa payment prompts are for whole shillings; any cents rounded up are shown on the receipt as change due. '}
        {info?.return_policy ? <>Returns and refunds: {info.return_policy}</> : 'Returns and refunds follow the shop’s returns policy and the Consumer Protection Act, 2012.'}
      </p>

      <h2>Records and monitoring</h2>
      <p>
        Actions in the system are logged for security and accounting. Managers may review these logs. Records are kept
        as tax law requires.
      </p>

      <h2>Changes</h2>
      <p>The shop may update these terms; the date above shows the latest version.</p>
    </LegalLayout>
  );
}

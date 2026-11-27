# Legal and compliance checklist

Reviewed 27 November 2026 against a common "20 things so your app doesn't get sued" list,
for what Smart Inventory is: an internal system used by one supermarket's staff in Kenya
(Data Protection Act 2019, Consumer Protection Act 2012, Kenyan tax law). This is an
engineering review, not legal advice: the shop should have the privacy notice and terms
checked by a lawyer before relying on them.

| # | Item | Status | Where / what was done |
|---|---|---|---|
| 1 | Terms of service | Done | `/terms` page, linked from every page footer and the sign-in screen: staff accounts, acceptable use, AI use, monitoring |
| 2 | Privacy policy | Done | `/privacy` page: data held (staff, customers, suppliers, AI), purposes and lawful basis, sharing (Safaricom, Anthropic shown only when switched on), retention, cookies, security, rights, ODPC complaint. Contact from `PRIVACY_CONTACT` |
| 3 | Cookie consent banner | Not needed | One strictly necessary HttpOnly sign-in cookie; no analytics, advertising or third-party cookies; nothing kept in browser storage. Explained in the privacy notice |
| 4 | Age check at sign-up | Not applicable | No public sign-up: only the administrator creates accounts, for employees |
| 5 | Delete account | Done | Administration → Users → *Erase personal data* for deactivated staff: name, username, e-mail, phone, password, sessions and IPs erased, and old audit snapshots redacted; sales and accounting records kept as tax law requires |
| 6 | Remove fake reviews | Checked | The system shows no reviews, ratings or testimonials. Demo data is clearly marked "(Demo)" and only created by an explicit command |
| 7 | Refund policy | Done | `RETURN_POLICY` setting printed on every receipt and shown in the terms; returns workflow with manager approval already exists |
| 8 | Easy cancel button | Not applicable | No subscriptions or recurring charges. M-Pesa prompts can be declined on the customer's phone, and the till can cancel and use another method |
| 9 | Audit third-party SDKs | Done | `npm audit --omit=dev`: 0 vulnerabilities; `pip-audit -r requirements.txt`: no known vulnerabilities. Outside services listed in the privacy notice |
| 10 | Hide API keys | Verified | All keys only in the server's `.env` (git-ignored; Git history checked: never committed). The browser bundle contains no secrets; AI, M-Pesa and archive calls go through the server |
| 11 | Encrypt passwords | Verified | Argon2 hashing (`backend/app/core/security.py`); passwords are never stored or logged in readable form |
| 12 | Remove hidden fees | **Fixed** | M-Pesa prompts round cents up to whole shillings; the rounded-up cents were not shown on the receipt. Now the receipt shows the amount paid and "Change due (M-Pesa rounding)", the till tells the cashier, and the terms explain it. Prices include VAT and the receipt shows the VAT |
| 13 | Unsubscribe link in emails | Not applicable | The system sends no e-mails (password-reset links are handed over by the administrator) and no marketing messages |
| 14 | Accessibility alt text | Checked | Every image has alt text (product photos, invoice pages, receipt attachments); icons are marked decorative. Earlier accessibility audit in `docs/website-audit.md` |
| 15 | AI content disclaimer | Done | AI assistant: "The AI can make mistakes: check figures before you confirm", proposals need a person's Confirm. AI-read invoices are labelled "AI-generated: check every field against the paper". Terms of use cover AI use |
| 16 | Remove dark patterns | Checked | No pre-ticked consents, no hidden costs, no forced continuity; Confirm and Cancel are equally visible; destructive actions ask for confirmation with plain consequences |
| 17 | License fonts/images | Checked | No font files shipped (system fonts); Lucide icons (ISC); own logo; synthetic sample data. Full list: `docs/third-party-licences.md` |
| 18 | Data breach plan | Done | `docs/data-breach-plan.md`: roles, containment steps for this system, 72-hour notification to the ODPC, telling affected people, recovery, records |
| 19 | Marketing email consent | Not applicable | No marketing. The privacy notice states that customer phone numbers are not used for marketing |
| 20 | Remove unsupported claims | Checked | No claims of guarantees or certifications in the interface. OCR accuracy figures in the README are labelled as results on synthetic test invoices, and the AI reader is stated as not yet measured |

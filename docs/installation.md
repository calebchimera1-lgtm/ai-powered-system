# Installation and operation

This guide installs the system on one computer (a laptop or a small office server) with Docker.
It was followed from a fresh clone at the end of Phase 6; the results are at the end of this
guide.

## 1. What you need

| | Minimum | Recommended |
|---|---|---|
| Operating system | Windows 10/11 (WSL 2), macOS 12+, or 64-bit Linux | Ubuntu 22.04/24.04 server |
| Memory | 4 GB RAM (the stack uses about 1.5 GB) | 8 GB |
| Disk | 5 GB free | 20 GB (room for invoices, photos and backups) |
| Software | [Docker Desktop](https://docs.docker.com/get-docker/) or Docker Engine 24+ with Compose v2, and Git | |
| Network | Internet access for the first build (downloads packages) | |

No GPU is needed. Everything, including OCR and machine learning, runs on the CPU.

## 2. Install

### Step 1: get the code

```bash
git clone <repository URL> smart-inventory
```

```bash
cd smart-inventory
```

### Step 2: create the settings file (`.env`) with random secrets

On Linux or macOS:

```bash
make env
```

Without `make` (for example on Windows): copy `.env.example` to `.env`, then replace the three
`CHANGE_ME` values with long random strings. Python can generate them:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Then open `.env` and set at least:
- `STORE_NAME`, `STORE_ADDRESS`, `STORE_PHONE` and `STORE_KRA_PIN`. These are printed on receipts and reports.
- `FRONTEND_URL`, the address staff will type into the browser (for example `http://192.168.1.20:8080`). It is used for password-reset links.
- `WEB_PORT`, if port 8080 is already taken.

Keep `.env` private. It holds the database passwords and the token signing key, and it is
never committed to Git.

In production (`ENVIRONMENT=production`) the API **refuses to start** if `JWT_SECRET` is a
placeholder or shorter than 32 characters, or if the database password is a default or shorter
than 12 characters. The error names the setting, never its value.

The application connects to PostgreSQL as its own role, `APP_DB_USER`, which is not a
superuser. `POSTGRES_USER` remains the administrator account, used only for maintenance.

### Step 3: build and start

```bash
docker compose up -d --build
```

The first build downloads and installs everything, including Tesseract OCR and the Python
and JavaScript packages. Expect 5 to 15 minutes. Later starts take seconds. Check that all
four containers are up:

```bash
docker compose ps
```

`db`, `api` and `web` should show `healthy`, and `worker` `running`. The API applies the
database migrations itself when it starts.

### Step 4: create the first Super Administrator

```bash
docker compose exec api python -m scripts.create_superadmin
```

It asks for a name, username, email and password, and checks the password's strength.

### Step 5: sign in

Open `http://localhost:8080` on the same computer, or the `FRONTEND_URL` from another device
on the network. Sign in, then add your staff under **Administration → Users**. Each person
gets a role (Store Manager, Inventory Officer or Cashier) and must change their temporary
password the first time they sign in.

### Optional: demonstration data

For a presentation or training session only, never on a real store's database:

```bash
docker compose exec -e ENVIRONMENT=development api python -m scripts.seed_demo_users
```

```bash
docker compose exec -e ENVIRONMENT=development api python -m scripts.seed_demo_catalog --history-days 180
```

This creates:
- one demo account per role, all with the password `Demo@2026!`
- 10 demo products and 3 demo suppliers, all marked "(Demo)"
- 180 days of simulated trading, which takes about 2 minutes

The worker then prepares a forecast and an irregularity scan. Sample invoices to try scanning
are in `sample-data/invoices/`. The scripts refuse to run when `ENVIRONMENT=production` is
set without the override shown.

## 3. Everyday operation

| Task | Command |
|---|---|
| Stop the system (data is kept) | `docker compose stop` |
| Start it again | `docker compose start` |
| See what it is doing | `docker compose logs -f --tail=100` |
| Is it healthy? | `docker compose ps` |
| API documentation (interactive) | `http://localhost:8080/api/docs` |

The worker runs these jobs on its own:
- every night: back up, forecast and clean up
- every 3 hours: scan for irregularities
- every 15 minutes: check expiry dates and waiting approvals

## 4. Backups and recovery

**Automatic.** Every night the worker writes a backup into the `storage` volume. Each backup
contains:
- the database, as a `pg_dump` custom-format file
- an archive of the uploaded files (photos, invoices)
- a manifest with checksums

The dump is checked to be readable. The system keeps 7 nightly backups, one per week for 4
weeks, and the last 5 manual ones. A Super Admin sees them under **Administration →
Backups**, can make one now, and can download them.

**Keep a copy elsewhere.** A backup on the same disk does not survive a disk failure or a
theft. Copy backups off the machine regularly, at least weekly: download them from the
Backups page, or run:

```bash
docker compose cp api:/app/storage/backups ./backups-copy
```

**Restore.** This replaces all current data with the backup. Use it after a disaster, or to
move to a new computer (install the system there first, then copy the backup folder into
`storage/backups`):

```bash
make backups
```

```bash
make restore NAME=20261108-020000-daily
```

`make restore` stops the app, checks the backup's checksums, then restores the database in a
single transaction (if anything fails, nothing changes) and the uploaded files. It then
applies any newer migrations and starts the app again. Without `make`, run the four commands
from the `restore:` section of the `Makefile`.

## 5. Updating to a new version

```bash
git pull
```

```bash
docker compose up -d --build
```

Migrations run automatically. Make a manual backup first (Backups page → **Back up now**).

**Installations created before the security update** connect to the database as the
PostgreSQL superuser. Move them to the least-privilege role once, after updating:
1. Add `APP_DB_USER=inventory_app` and `APP_DB_PASSWORD=<a long random value>` to `.env`.
2. Run the command below. It only changes role settings and table ownership, not data.

```bash
make db-least-privilege
```

Until then the API logs a warning at startup.

## 6. Using it over a network or the internet

On a shop's local network, staff open `http://<server-ip>:8080`. Set `FRONTEND_URL` to that
address.

Anything reachable from outside the shop **must** use HTTPS. Put a TLS-terminating reverse
proxy in front of the `web` container (Caddy, Traefik or nginx with a certificate, for
example from Let's Encrypt), then in `.env` set:
- `COOKIE_SECURE=true`
- `FRONTEND_URL=https://your.domain`

The proxy must pass `X-Forwarded-Proto: https`; the `web` container then adds
`Strict-Transport-Security`. Because the `web` container treats the address it sees as the
client's, add the proxy's address to nginx's `set_real_ip_from` (with
`real_ip_header X-Forwarded-For`) so per-IP rate limits apply to real clients rather than
to the proxy. Ask Super Administrators and managers to turn on two-step sign-in
(My account).

These proxy set-ups are standard but were not part of this project's tests.

## 6a. M-Pesa payment prompt (STK push), optional

With this set up, the cashier types the customer's phone number and the customer gets an
M-Pesa PIN prompt on their phone ("Lipa Na M-Pesa Online"). Without it, the till still
accepts M-Pesa by the transaction code from the customer's SMS.

1. Create an account on the Safaricom Daraja portal (developer.safaricom.co.ke) and an app
   with *Lipa Na M-Pesa Sandbox*. The portal's test credentials page gives the sandbox
   shortcode and passkey.
2. In `.env`, set `MPESA_CONSUMER_KEY`, `MPESA_CONSUMER_SECRET`, `MPESA_SHORTCODE` and
   `MPESA_PASSKEY`, keep `MPESA_ENVIRONMENT=sandbox`, and restart the API:

```bash
docker compose up -d api
```

3. Test with a real Safaricom phone number on the sandbox: sell an item, choose M-Pesa,
   send the prompt, and accept it on the phone (sandbox prompts do not take real money).
4. To go live, apply for Lipa Na M-Pesa Online on Daraja for the shop's own paybill or
   till. Then set `MPESA_ENVIRONMENT=production` and the production key, secret, shortcode
   and passkey. For a till, also set `MPESA_TRANSACTION_TYPE=CustomerBuyGoodsOnline` and
   `MPESA_TILL_NUMBER`.

**Results.** By default the app asks Safaricom for the result every few seconds while the
till waits, so no public address is needed. For instant results, make the shop reachable on
HTTPS (section 6) and set `MPESA_CALLBACK_BASE_URL` (for example `https://shop.example.com`)
and `MPESA_CALLBACK_TOKEN` (a random value of at least 24 characters). Safaricom then calls
`/api/v1/payments/mpesa/callback/<token>`.

**Safety.** A sale can be completed with a prompt only after Safaricom reports it as paid,
for at least the sale total, and each payment can pay for one sale only. The keys stay on
the server and are never sent to the browser.

## 6b. Document archive (Paperless-ngx), optional

[Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) (open source, GPL-3.0) keeps
every receipt, invoice, contract and tax document scanned, OCR-read, tagged and searchable.
With it switched on:
- every supplier invoice approved in Smart Inventory is **filed automatically**, under its
  supplier, with the type *Supplier invoice*, the tags *supplier invoice* and *smart
  inventory*, the invoice date, and a title such as *Invoice SI/5040 · GRN-2026-000318*. The
  invoice page links to the filed copy.
- staff open **Document archive** in the menu (or `http://<server>:8090`) to upload, search
  and tag any other document.
- a scanner set to *scan to folder*, or anyone with access to the server, can drop files into
  the `archive-inbox` folder. They are read, filed and removed from the folder. Files in a
  subfolder get that folder's name as a tag (for example `archive-inbox/contracts/`).

It needs about 1–1.5 GB of extra memory.

1. In `.env`, set `PAPERLESS_SECRET_KEY` (a random value of 32+ characters),
   `PAPERLESS_ADMIN_PASSWORD` (12+ characters) and `PAPERLESS_PUBLIC_URL`, the address staff
   will use, for example `http://192.168.1.20:8090`. New `.env` files made with `make env`
   already have random values. Then start the archive (the first start takes a few minutes):

```bash
make archive
```

2. Create the token that lets Smart Inventory file invoices, and copy the printed token into
   `.env` as `PAPERLESS_TOKEN`:

```bash
make archive-token
```

3. Restart the app so it picks up the token:

```bash
docker compose up -d api worker
```

4. Optional: file the invoices that were approved before the archive existed:

```bash
make archive-backfill
```

Sign in to the archive with `PAPERLESS_ADMIN_USER` / `PAPERLESS_ADMIN_PASSWORD`, then create an
account for each member of staff who needs it (Settings → Users & Groups).

**If an invoice is not filed**, its page says why and an approver can press **Try again**. The
worker also retries by itself. Each invoice is only ever filed once.

**Backups.** The archive keeps its own data (Docker volumes `archive-data` and
`archive-media`); Smart Inventory's backups do not include it. Use Paperless's exporter:

```bash
docker compose --profile archive exec archive document_exporter ../export
```

## 6c. AI accounting assistant and AI invoice reading (Claude), optional

With a Claude API key the system gets:
- **AI assistant** (menu: Overview → AI assistant). Staff ask in plain English or Kiswahili:
  *"How much profit did we make this month?"*, *"Which products are running low?"*,
  *"Record KES 3,500 for transport today, paid by M-Pesa"*. Answers come only from the shop's
  own records, and each person's assistant can see only what their role allows (a cashier's
  assistant cannot see profit figures). Staff can attach a photo or PDF of a receipt or
  invoice: the assistant reads it, explains it, and prepares an expense or sends the invoice
  to *Scan invoices*. **Nothing is saved until a person presses Confirm.**
- **AI invoice reading.** Photos uploaded under *Purchasing → Scan invoices* are read with
  Claude vision, which copes much better with phone photos than plain OCR. If the AI cannot
  answer (no internet, no credit), Tesseract OCR reads the invoice instead, as before.
- **A complete log.** Every question, answer, attached file, record the AI looked at,
  proposal and confirmation is stored. Users with the audit permission can read everyone's
  conversations (AI assistant → *All staff*); proposals and confirmations also appear in
  the audit log.

1. Create an API key at <https://console.anthropic.com> (Settings → API keys) and add credit
   under Billing. Each question costs a small amount of credit.
2. Put it in `.env` (it is used only by the server and never sent to browsers):

```bash
ANTHROPIC_API_KEY=your-key-here
```

3. Restart the app:

```bash
docker compose up -d api worker
```

Optional settings: `ASSISTANT_MODEL` (default `claude-opus-5-5`), `ASSISTANT_EFFORT` (`low`,
`medium` (default), `high`), and `AI_INVOICE_READING=false` to keep reading invoices with
Tesseract only. Requests use Claude's server-side fallbacks: if the model declines a request,
Anthropic's fallback model answers it in the same call. Without a key, both features stay off
and the assistant page explains how to switch them on.

Privacy: questions, attached files and the figures the assistant looks up are sent to the
Claude API (Anthropic) to produce the answer. The records themselves stay in the shop's
database. Do not enable it if your data policy does not allow this.

## 7. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `port is already allocated` | Another program uses 8080: set `WEB_PORT` in `.env`, then `docker compose up -d` |
| `Set POSTGRES_PASSWORD in .env` | `.env` is missing or incomplete: step 2 |
| The build fails at `apt-get` or `pip install` | No internet access, or a proxy that Docker does not know about. Configure Docker's proxy settings and retry |
| The page loads but sign-in fails with "Cannot reach the server" | `api` is not healthy yet (it waits for the database and applies migrations): `docker compose logs api` |
| Invoices stay "Waiting to be read" | The worker is not running: `docker compose ps`, `docker compose logs worker`. If only the API runs (for example started from an editor), the API now reads invoices itself after a minute without a worker |
| `worker` or `api` keeps restarting with `exec ./docker-entrypoint.sh: no such file or directory` (Windows) | The script got Windows line endings. Pull the latest code (it includes `.gitattributes`), then `docker compose build --no-cache api` and `docker compose up -d` |
| A scanned invoice shows "Tesseract is not installed" | You are running the backend outside Docker: install Tesseract (`apt install tesseract-ocr`, or the Windows installer), or set `ANTHROPIC_API_KEY` so the AI reads invoices |
| "Take photo" does not open the camera | Phones only show the camera for pages opened over HTTPS or `localhost`. On a laptop the button opens the file picker; take the photo with the phone instead |
| The AI assistant says the key was refused or there is no credit | Check `ANTHROPIC_API_KEY` in `.env` and the credit at console.anthropic.com → Billing, then `docker compose up -d api worker` |
| Forecast says "low confidence" | Fewer than 8 weeks of sales recorded for that product; it improves with time |
| Out of memory on a 4 GB machine | Close other programs; the containers have memory limits that total about 1.7 GB |

## 8. Installation check (end of Phase 6)

This guide was followed from a fresh `git clone` of the repository on a clean Docker host.

| Step | Result |
|---|---|
| 2. `make env` | `.env` created; no `CHANGE_ME` left |
| 3. `docker compose up -d --build` | **Not run unchanged:** the build sandbox blocks Debian's package servers, so `apt-get` failed. The backend image was built from an equivalent Ubuntu 24.04 base with the same packages (Tesseract, fonts, PostgreSQL client), the web image with the standard Dockerfile, then `docker compose up -d --no-build`. All four containers became healthy |
| 4. Create the Super Administrator | Done (non-interactively, with `SUPERADMIN_PASSWORD`) |
| 5. Sign in | Home page and sign-in through the web container worked |
| Demo data | 180 days seeded in 2 min 10 s; the worker's forecast and irregularity scan then succeeded |
| `make backup`, `make backups`, `docker compose cp …` | Backup listed (1.0 MB) and copied off the container |
| `make restore NAME=…` | A product added after the backup was gone after the restore; the 10 products and 9,134 sales were back; the app restarted healthy in about 13 seconds |

The one step not verified as written is the image build on a normal internet connection. It
uses the standard `python:3.12-slim` base and Debian packages, and is expected to work.

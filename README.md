# AI-Driven Smart Inventory Management and Automated Receipt Digitization System

An inventory platform for supermarkets: inventory, POS, procurement, AI receipt/invoice digitization (OpenCV + OCR), demand forecasting, anomaly detection and financial analytics in KES.

**Stack:** React + TypeScript + Tailwind · FastAPI + SQLAlchemy + Alembic · PostgreSQL 16 · Docker Compose
(OCR and ML libraries are added in Phases 4–5.)

The full architecture, ERD and AI strategy are in [docs/00-system-design-plan.md](docs/00-system-design-plan.md).

## Status

| Phase | Scope | State |
|---|---|---|
| 1. Foundation | Docker stack, database + migrations, authentication, role-based access, user management, password reset, sessions, audit log, worker queue, app shell | **Done** |
| 2. Core inventory | Products (SKU, barcodes, photos, min/max, expiry), categories, suppliers and their prices, append-only stock ledger with weighted average cost, expiry batches (oldest first), stock counts and adjustments with manager approval, damaged/expired write-offs | **Done** |
| 3. Sales & procurement | Point of sale (barcode, cash/M-Pesa/card, discounts, VAT, receipts), sales history and cash-up, returns with manager approval, purchase orders, goods received (stock, average cost, batches, supplier prices, price-change and duplicate-invoice checks), expenses, profit analytics | **Done** |
| 4. AI receipt digitization | Invoice upload/photo, OpenCV + OCR extraction, product matching, review and approval | Next |
| 5–6 | Forecasting and anomaly detection, dashboard, reports, finalization | Planned |

## Quick start (Docker)

Requirements: Docker 24+ with Compose v2, Git, 4 GB RAM minimum (8 GB recommended).

1. Create `.env` with random secrets (or copy `.env.example` and edit it):

```bash
make env
```

2. Build and start the database, API, worker and web server:

```bash
docker compose up -d --build
```

3. Create the first Super Administrator (it prompts for the details and password):

```bash
docker compose exec api python -m scripts.create_superadmin
```

4. Open http://localhost:8080 and sign in.

Optional, for demonstrations only: create one **demo** account per role (password `Demo@2026!`) and a small **synthetic** catalogue (10 products incl. sugar, rice, cooking oil, maize flour, milk, bread, soap and bottled water; 3 demo suppliers). Never run these on a real store's database.

```bash
docker compose exec -e ENVIRONMENT=development api python -m scripts.seed_demo_users
```

```bash
docker compose exec -e ENVIRONMENT=development api python -m scripts.seed_demo_catalog --history-days 60
```

`--history-days` (optional, up to 730) simulates that many days of trading through the real services: sales with weekly and month-end patterns, deliveries, returns and expenses. It is seeded, so it produces the same data every time. 60 days takes about a minute.

API documentation (OpenAPI) is available at http://localhost:8080/api/docs.

Stop the stack with `docker compose down`. Data is kept in Docker volumes; `docker compose down -v` deletes it.

## How staff accounts work

- Only a **Super Administrator** creates accounts (Users → Add staff member). Store Managers can view them.
- By default a new account gets a **one-time setup link** (valid 30 minutes) to hand to the staff member, who chooses their own password. Alternatively, set a temporary password, which must be changed at first sign-in.
- Forgotten password: an administrator opens the user's ⋯ menu → *Create reset link*.
- Five wrong passwords lock an account for 15 minutes; an administrator can unlock it sooner.
- Deactivating an account or choosing *Sign out everywhere* takes effect immediately.
- Every sign-in, failed sign-in and administrative change is recorded in the **Audit log**.

## Development

Backend (Python 3.12, needs a local PostgreSQL 16):

```bash
cd backend && python3.12 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
```

```bash
alembic upgrade head && uvicorn app.main:app --reload
```

Frontend (Node 20+), proxies `/api` to `localhost:8000`:

```bash
cd frontend && npm install && npm run dev
```

Alternatively, `make dev` runs the database and API in Docker with hot reload.

## Tests

Backend tests run against a real PostgreSQL database (`inventory_test`, created automatically). Set `TEST_DATABASE_URL` to use a different server.

```bash
cd backend && python -m pytest
```

```bash
cd frontend && npm test
```

Current results (end of Phase 3): **189 backend tests** and **58 frontend tests**, all passing. They include hand-computed weighted-average-cost and margin checks, oldest-expiry-first batch deduction, the negative-stock guard, the append-only ledger trigger, and two concurrency tests (two tills selling the last stock at the same moment cannot oversell).

Each phase is also exercised end-to-end in a real browser against the Docker stack. Phase 3: scanning at the till (including rapid repeat scans), cash and M-Pesa sales, a cashier return approved by a manager, a purchase order received in part with a supplier price rise flagged, a duplicate supplier invoice refused, expenses, the profit page, and the till at phone width. Phase 2: barcode/typo search, creating a product with opening stock, photo upload, barcode generation, a count correction, a large adjustment held for and approved by a manager, a write-off, and the cashier's read-only phone view.

## How stock works

- Stock changes only through ledger movements (opening stock, receipts, sales, returns, adjustments, write-offs). Each records who, when, how much and the running balance. The database refuses edits or deletions of ledger rows.
- Cost of stock uses the **weighted average cost** (WAC): each receipt blends its price into the average; sales and write-offs are valued at the current average.
- Perishables can **track expiry**: each delivery is a batch, and sales and write-offs take the oldest-expiring stock first.
- Stock cannot go below zero unless a Super Administrator explicitly authorises it.
- Manual adjustments worth more than **KES 5,000** at cost wait for a Store Manager's approval (configurable: `STOCK_ADJUSTMENT_APPROVAL_THRESHOLD`). Nobody can approve their own request.
- Cashiers see prices and stock levels, never costs or margins.

## How sales and profit work

- Shelf prices include VAT; VAT is extracted per line (`price × rate / (100 + rate)`). A whole-sale discount is spread across lines in proportion to their value, so each line's VAT stays correct.
- Each sale records the cost of every line at that moment (weighted average cost), so profit is exact even when supplier prices change later.
- Cashiers may discount up to **10%** (`MAX_CASHIER_DISCOUNT_PERCENT`); more needs a Store Manager and is recorded in the audit log.
- The till sends a one-time request id with each sale, so a double-click or a network retry can never record the same sale twice. Two tills selling the last items at the same moment cannot oversell.
- Returns refund the discounted price actually paid. Resaleable items go back into stock (into their original expiry batch); damaged items are refunded but count as a stock loss. Cashiers' returns wait for a manager.
- Supplier costs are entered **excluding VAT** (input VAT is reclaimable). The same supplier invoice number cannot be received twice, and cost changes of **10%** or more are flagged (`PRICE_CHANGE_ALERT_PERCENT`).
- Profit definitions: Revenue = sales excluding VAT, minus refunds excluding VAT. Gross profit = Revenue − cost of goods sold. Net profit (estimate) = gross profit − stock losses ± stock adjustments − operating expenses.
- Receipt header details come from `.env`: `STORE_NAME`, `STORE_ADDRESS`, `STORE_PHONE`, `STORE_KRA_PIN`, `RECEIPT_FOOTER`.

## Security notes

- Passwords: Argon2id. Tokens: 15-minute JWT access token kept in memory + rotating refresh token in an HttpOnly, SameSite=Strict cookie, stored hashed server-side. Reuse of an old refresh token revokes the session.
- Secrets come only from `.env` (git-ignored). In production mode the API refuses to start with the default JWT secret.
- When serving over HTTPS, set `COOKIE_SECURE=true` and `FRONTEND_URL=https://…` in `.env`.

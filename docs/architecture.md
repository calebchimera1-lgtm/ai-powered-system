# System architecture

This describes the system **as built**. The original design and its reasoning are in
[00-system-design-plan.md](00-system-design-plan.md). Diagrams use Mermaid, which GitHub,
GitLab and most Markdown editors render.

## 1. Architecture diagram

The design is a modular monolith: one FastAPI code base, run as two processes (the API and a
background worker), behind nginx. It uses PostgreSQL 16 and a file-storage volume. Everything
runs with `docker compose up` on one laptop or a small server.

```mermaid
flowchart LR
    subgraph Clients
        B["Browser: React + TypeScript<br/>(desktop, tablet, phone camera)"]
        S["USB barcode scanner<br/>(acts as a keyboard)"]
    end
    subgraph Docker host
        W["web: nginx<br/>static app, /api proxy,<br/>security headers"]
        A["api: FastAPI (2 workers)<br/>auth · RBAC · validation<br/>REST /api/v1"]
        K["worker: same code<br/>job queue · schedule<br/>OCR · forecasting · anomalies<br/>notifications · backups"]
        D[("db: PostgreSQL 16<br/>ledger, sales, invoices,<br/>forecasts, alerts, jobs")]
        F[["storage volume<br/>product photos, invoices,<br/>backups"]]
    end
    S --> B
    B -- HTTPS --> W -- /api --> A
    A -- SQL --> D
    K -- SQL --> D
    A -- enqueue job --> D
    D -- "claim job (SKIP LOCKED)" --> K
    A -- uploads --> F
    K -- page images, backups --> F
```

| Part | Technology | What it does |
|---|---|---|
| Frontend | React 18, TypeScript, Tailwind, TanStack Query, Recharts, lucide | Role-aware screens; the access token is kept in memory only |
| API | FastAPI, SQLAlchemy 2, Pydantic 2 | Validation, permissions on every endpoint, business rules in a service layer |
| Worker | Same code base, `python -m app.workers.runner` | Postgres-backed job queue (`background_jobs`, `FOR UPDATE SKIP LOCKED`), retries, periodic jobs |
| AI | OpenCV, Tesseract 5, pdfplumber, RapidFuzz; pandas, statsmodels, scikit-learn | OCR pipeline; forecasting models; Isolation Forest. All CPU-only |
| Database | PostgreSQL 16, Alembic migrations | Append-only stock ledger enforced by a trigger, check constraints, sequences |
| Files | Docker volume `storage` | Served only to signed-in users with the right permission (no public URLs) |

**Code layout (backend).**
- `app/api/v1/` holds HTTP routes only.
- `app/services/` holds the business rules. All stock changes go through one function, `inventory_service.apply_movement`.
- `app/ai/` holds pure engines (OCR, forecasting, anomaly detection) that have no database access, so they can be unit-tested and evaluated on their own.
- `app/workers/` has the job handlers and the schedule.
- `app/reports/` has the PDF, Excel and CSV writers.

## 2. Use-case diagram

```mermaid
flowchart LR
    SA(["👤 Super Admin"])
    SM(["👤 Store Manager"])
    IO(["👤 Inventory Officer"])
    CA(["👤 Cashier"])
    WK(["⚙ Worker (system)"])
    subgraph SYS["Smart Inventory System"]
        U1([Manage users and roles])
        U2([Back up the system])
        U3([View audit log])
        U4([View dashboard and reports])
        U5([Review irregularities])
        U6([Approve returns and large adjustments])
        U7([Manage products, suppliers, purchase orders])
        U8([Scan and approve supplier invoices])
        U9([Receive goods, adjust stock, write off])
        U10([View forecasts and reorder])
        U11([Sell at the till])
        U12([Request customer returns])
        U13([Read and extract invoices: OCR])
        U14([Forecast demand, scan for irregularities])
        U15([Send notifications])
    end
    SA --- U1 & U2 & U3
    SA --- U4
    SM --- U4 & U5 & U6 & U7 & U11
    IO --- U7 & U8 & U9 & U10
    IO --- U4
    CA --- U11 & U12
    U8 -. includes .-> U13
    WK --- U13 & U14 & U15 & U2
```

The Super Admin can also do everything a Store Manager can. The full permission matrix is in
[00-system-design-plan.md](00-system-design-plan.md) section 2 and in
`backend/app/core/permissions.py`.

## 3. Data flow diagrams

### Level 0 (context)

```mermaid
flowchart LR
    Staff(["Staff<br/>(4 roles)"])
    Supplier(["Supplier"])
    Customer(["Customer"])
    SYS(("Smart Inventory<br/>System"))
    Staff -- "products, counts, approvals, reviews" --> SYS
    SYS -- "dashboard, reports, alerts, forecasts" --> Staff
    Supplier -- "invoice (paper / PDF)" --> Staff
    Staff -- "photo / PDF of invoice" --> SYS
    SYS -- "purchase order" --> Supplier
    Customer -- "items, payment" --> Staff
    SYS -- "receipt" --> Customer
```

### Level 1

```mermaid
flowchart TB
    Staff(["Staff"])
    P1["1 Digitize invoice<br/>(OCR, extract, match)"]
    P2["2 Review and approve"]
    P3["3 Record stock movement<br/>(ledger, WAC, batches)"]
    P4["4 Sell / return"]
    P5["5 Forecast and plan<br/>reorders"]
    P6["6 Detect irregularities"]
    P7["7 Report and notify"]
    D1[("Invoices + files")]
    D2[("Stock ledger,<br/>products, batches")]
    D3[("Sales, returns")]
    D4[("Forecasts")]
    D5[("Alerts, notifications")]
    Staff -- invoice image --> P1 --> D1
    D1 --> P2
    Staff -- corrections --> P2 -- goods received --> P3
    Staff -- sale --> P4 -- sale out / return in --> P3
    P4 --> D3
    P3 --> D2
    D3 --> P5 --> D4
    D2 --> P6
    D3 --> P6 --> D5
    D2 & D3 & D4 & D5 --> P7 -- "dashboard, reports, bell" --> Staff
```

## 4. Key flows

**Stock.** Every change is a row in `stock_movements`. The table is append-only (a database
trigger refuses updates and deletes). Each change goes through `apply_movement`, which:
- locks the product row
- recalculates the weighted average cost on receipt
- takes stock from the oldest-expiring batch first on sale
- refuses negative stock unless an administrator explicitly allows it
- raises a low-stock notification when the line is crossed

**Sales.** Prices include VAT, and VAT is extracted per line. Each line stores its cost at the
moment of sale, so profit is exact even when supplier prices change later. Checkout is
idempotent (a one-time request id), and two tills cannot oversell the last item.

**Invoice digitization.** See [ai/ocr-methodology.md](ai/ocr-methodology.md) for the full
workflow diagram:

```mermaid
flowchart LR
    U[Upload / photo] --> C{Checks:<br/>type, size, duplicate}
    C --> Q[(Job queue)] --> P[OpenCV clean-up] --> T[Tesseract OCR<br/>or PDF text]
    T --> X[Extract fields and lines] --> M[Match supplier and products] --> V[Validate:<br/>arithmetic, totals, duplicates]
    V --> R[Human review] -->|approve| G[Goods received:<br/>stock, cost, batches]
    R -->|reject| Z[Rejected with reason]
```

**Forecasting and irregularities.**
- Every night the worker backtests six forecasting models per product and keeps the best one. It then stores 28-day forecasts and reorder advice, and sends shortage notifications.
- Every three hours it compares each product's and each person's day with their own normal, using rules and an Isolation Forest.
- See [ai/forecasting-and-anomalies.md](ai/forecasting-and-anomalies.md).

## 5. Security

| Area | Measure |
|---|---|
| Passwords | Argon2id hashes; strength rules; forced change of temporary passwords |
| Sessions | 15-minute access token kept in memory; rotating refresh token in an HttpOnly, SameSite=Strict cookie limited to `/api/v1/auth`; reuse of an old refresh token revokes the session |
| CSRF | Custom `X-Requested-With` header required; strict cookies |
| Access control | Permission check on every endpoint (server side), not only hidden buttons; staff-related irregularities limited to reviewers; nobody approves their own return or reviews an alert about themselves |
| Input | Pydantic validation; SQLAlchemy parameters (no string-built SQL from user input); uploads checked by content (magic bytes), size and page count, stored outside the web root with random names |
| Abuse | Rate limits on sign-in, password reset and report generation |
| Transport and browser | nginx security headers: CSP, X-Frame-Options DENY, nosniff, Referrer-Policy; TLS in deployment (see installation guide) |
| Secrets | From environment variables (`.env`, never committed); the frontend contains no secrets or database credentials |
| Audit | Sign-ins, user changes, stock adjustments, approvals, price changes, report exports and backups are written to `audit_logs` |
| Recovery | Nightly verified backups with rotation; tested restore procedure |

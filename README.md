# AI-Driven Smart Inventory Management and Automated Receipt Digitization System

An inventory platform for supermarkets: inventory, POS, procurement, AI receipt/invoice digitization (OpenCV + OCR), demand forecasting, anomaly detection and financial analytics in KES.

**Stack:** React + TypeScript + Tailwind · FastAPI + SQLAlchemy + Alembic · PostgreSQL 16 · Docker Compose
(OCR and ML libraries are added in Phases 4–5.)

The full architecture, ERD and AI strategy are in [docs/00-system-design-plan.md](docs/00-system-design-plan.md).

## Status

| Phase | Scope | State |
|---|---|---|
| 1. Foundation | Docker stack, database + migrations, authentication, role-based access, user management, password reset, sessions, audit log, worker queue, app shell | **Done** |
| 2. Core inventory | Products, categories, suppliers, stock ledger | Next |
| 3–6 | Sales & procurement, AI receipt digitization, analytics, finalization | Planned |

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

Optional, for demonstrations only: create one **demo** account per role (password `Demo@2026!`). Never run this on a real store's database.

```bash
docker compose exec -e ENVIRONMENT=development api python -m scripts.seed_demo_users
```

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

Phase 1 results: **85 backend tests** (unit + API integration + migrations + worker) and **28 frontend tests**, all passing. The full flow was also exercised in a real browser against the Docker stack: sign-in, session restore, creating a user, the setup link on a phone, the deactivation confirmation, the audit log and the cashier's restricted menus.

## Security notes

- Passwords: Argon2id. Tokens: 15-minute JWT access token kept in memory + rotating refresh token in an HttpOnly, SameSite=Strict cookie, stored hashed server-side. Reuse of an old refresh token revokes the session.
- Secrets come only from `.env` (git-ignored). In production mode the API refuses to start with the default JWT secret.
- When serving over HTTPS, set `COOKIE_SECURE=true` and `FRONTEND_URL=https://…` in `.env`.

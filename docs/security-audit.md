# Security audit

Audit of the whole system: the React frontend, the FastAPI backend and its 105 API routes,
authentication, the PostgreSQL database, dependencies, the Docker/nginx deployment and the Git
repository. Every finding below was reproduced before it was fixed and re-tested afterwards,
on the unit/integration test suites **and** against the running production Docker stack
(nginx + API + worker + PostgreSQL). No secret values appear in this report.

## Summary

| Severity | Found | Fixed | Remaining (accepted / needs an operator) |
|---|---|---|---|
| Critical | 0 | — | — |
| High | 2 | 2 | — |
| Medium | 5 | 5 | existing installs must run `make db-least-privilege` once |
| Low | 6 | 6 | — |

## Vulnerabilities found and fixed

| # | Severity | Finding | Fix | Verified by |
|---|---|---|---|---|
| 1 | **High** | **Client IP spoofing.** nginx *appended* to a client-supplied `X-Forwarded-For` and the API trusted it. Sending two requests with forged headers put `6.6.6.1` and `6.6.6.2` in the audit log; rotating the header gave a fresh per-IP sign-in limit on every request (password-guessing across accounts was effectively unthrottled). | nginx now sets `X-Forwarded-For`/`X-Real-IP` to the address it actually saw. | Live: forged headers now log the real client address. |
| 2 | **High** | **Vulnerable dependencies.** `pip-audit`: 86 advisories in 6 packages, including **Pillow** (53, decodes every uploaded photo and invoice scan), **python-multipart** (6, parses every upload), **pdfminer.six** (2, parses uploaded supplier PDFs), **PyJWT** (17), **Starlette** (7). `npm audit`: 11 (2 critical in test tooling; high in axios, react-router open redirect, zod memory exhaustion). | Upgraded to patched versions, including the majors needed (React Router 7, zod 4, pypdfium2 5, vitest 5) with the small code changes they required. | `pip-audit` and `npm audit`: **0 known vulnerabilities**. All 309 backend and 78 frontend tests pass on the new versions. |
| 3 | Medium | **The app connected to PostgreSQL as a superuser.** No SQL injection was found, but if one ever appeared, a superuser can read server files and run programs (`COPY … PROGRAM`). | New role `APP_DB_USER` (no SUPERUSER/CREATEROLE/CREATEDB/REPLICATION) owns the app database. Created automatically on new installs; `make db-least-privilege` migrates existing ones (ownership changes only, no data changes). The API logs a warning while it is still a superuser. | Live: API and worker connect as `inventory_app` (`rolsuper = f`), migrations, a backup, a download and a full restore all work under it; row counts identical after restore. |
| 4 | Medium | **Weak production secrets accepted.** Only the code's own default JWT secret was refused; the `.env.example` placeholders, short secrets and default DB passwords were accepted. | In production the API refuses to start with a placeholder or < 32-char `JWT_SECRET`, or a default / placeholder / < 12-char database password. Messages name the setting, never its value. | Unit tests, including that the message never contains the secret. |
| 5 | Medium | **Missing throttles.** No limit on guessing the current password through *change password* (with a stolen 15-minute access token); none on expensive jobs (OCR uploads, backups, forecast runs, anomaly scans), so one account could exhaust the server. | Per-user limits: change password 5 / 15 min, two-step setup/disable 10 / 15 min, invoice upload/reprocess 20 / min, backups 3 / 10 min, forecasts and scans 5 / min; token refresh 60 / min per IP. nginx adds per-IP limits: 20 req/s (burst 100) on the API and 10/min (burst 20) on sign-in and password reset, answering with JSON 429 + `Retry-After`. | Integration tests for each limit; live: the 22nd rapid sign-in got nginx's JSON 429 while other API traffic kept working. |
| 6 | Medium | **No multi-factor authentication.** | Optional two-step sign-in with authenticator-app codes (TOTP, RFC 6238, standard library only, no new dependency). Code asked only after a correct password; wrong or reused codes count toward the account lockout; each 30-second code works once; turning it on signs out other devices; turning it off needs password + code; a Super Admin can reset it for a lost phone. | RFC 6238 test vectors; 11 integration tests; live browser test of setup → sign-in with code → rejected wrong and replayed codes → disable. |
| 7 | Medium | **Security headers missing on HTML pages** (nginx drops server-level `add_header` in any `location` with its own), and duplicated on API responses (a doubled `X-Frame-Options` can be ignored by browsers). | One header snippet included everywhere; API copies hidden. Added `Strict-Transport-Security` (HTTPS requests only), `Cross-Origin-Opener-Policy`, `object-src 'none'`. | Live `curl`: each header exactly once on HTML, API and static files; HSTS present only with HTTPS. |
| 8 | Low | Interactive API docs and the full OpenAPI schema were public in production. | Off in production unless `EXPOSE_API_DOCS=true`. | Live: `/api/docs`, `/api/redoc`, `/api/openapi.json` → 404. |
| 9 | Low | Password-reset tokens travelled in the query string, so web-server access logs and proxies recorded them. | Token moved to the `#fragment` (never sent to a server); the page removes it from the address bar after reading. Old links keep working. | Live browser test: no request contained the token; address bar cleaned. |
| 10 | Low | The refresh cookie was `Secure` only if `COOKIE_SECURE` was set by hand, even on HTTPS. | Automatically `Secure` on HTTPS requests. | Integration tests (HTTPS → Secure, HttpOnly, SameSite=Strict, path-scoped; HTTP still works). |
| 11 | Low | Dev compose published PostgreSQL and the API on every network interface. | Bound to `127.0.0.1`. | Config review. |
| 12 | Low | Dotfiles, source maps and backup/config/log leftovers would be served if one ever landed in the web root. | nginx returns 404 for them (without shadowing `/api/` or `/assets/`). | Live: `/.env`, `/.git/config`, `*.map`, `*.sql`, `*.bak`, `*.log`, `*.yml` → 404; backup downloads (`.gz`, `.dump`) still work. |
| 13 | Low | A deprecated Starlette status constant logged a warning on every start after the upgrade. | Renamed (same 422 status). | Clean startup logs. |

## Checked and already secure (no change needed)

- **Passwords:** Argon2id (argon2-cffi defaults; rehash on login when parameters change); never stored or logged in plain text; policy: 8–128 characters, letters mixed with numbers/symbols, not common, not containing the username; reset links are single-use, hashed in the database, expire in 30 minutes, and resetting signs out every device.
- **Sign-in:** same message for unknown user and wrong password, with a dummy hash to equalise timing; 5 failures lock the account for 15 minutes (stored in the database).
- **Sessions:** 15-minute access token kept only in memory; refresh token in an HttpOnly, SameSite=Strict cookie limited to `/api/v1/auth`, stored only as a SHA-256 hash, rotated on every use with reuse detection; every request re-checks the server-side session, so sign-out, deactivation and admin revocation take effect immediately.
- **CSRF:** the API authenticates with a bearer header (not a cookie); the cookie endpoints also require `X-Requested-With` and SameSite=Strict.
- **Authorization (server side):** 99 of 105 routes require sign-in; the 6 public ones are health, sign-in, refresh, password reset and two image routes with unguessable names. A live probe of 36 cases passed: forged/`alg=none`/tampered/guessable-key tokens rejected; a cashier cannot reach admin, finance, purchasing or audit APIs, another cashier's sale by ID or receipt number, or restricted reports; a manager cannot manage users, backups or the audit log; nobody can change their own role; tokens die at sign-out.
- **Injection:** SQLAlchemy ORM and bound parameters throughout; the only string-built SQL uses fixed internal names.
- **XSS:** React escaping; no `dangerouslySetInnerHTML`/`innerHTML`/`eval`; print windows built with `textContent`; CSP `script-src 'self'`.
- **Input validation:** Pydantic on every body; oversized or malformed fields → 422 (checked live); 12 MB request cap.
- **Uploads:** type decided by file content, size-capped while reading, images re-encoded (metadata stripped, decompression bombs refused), PDFs capped at a page limit, path traversal blocked, restore uses the safe `tarfile` filter.
- **Secrets:** none in tracked files, in 14 commits of Git history, or in the frontend build (no `import.meta.env` use, no source maps); `.env` is git-ignored; **nothing was exposed, so no credentials needed rotating.**
- **Logs and audit trail:** no passwords, hashes, tokens or secrets in container logs or audit records (checked across every audit action); errors return a generic message, details only in server logs.
- **Containers:** API/worker run as an unprivileged user; the database has no published port.
- **Dependency upkeep:** every runtime dependency has released within the last 2.5 years; none is abandoned. Slowest-moving: pytesseract and openpyxl (2024), both widely used with no advisories.

## Files modified

Backend: `requirements*.txt`, `app/api/deps.py`, `app/api/v1/{auth,users,invoices,backups,forecasts,anomalies}.py`, `app/core/{config,rate_limit,exceptions,totp}.py`, `app/main.py`, `app/models/auth.py`, `app/schemas/{auth,users}.py`, `app/services/{auth_service,user_service,backup_service}.py`, `alembic/versions/20261112_0006_two_step_sign_in.py`, tests (`conftest.py`, `test_users.py`, new `test_security_hardening.py`, `test_mfa.py`).
Frontend: `package*.json`, `nginx.conf`, new `nginx/security-headers.conf`, `Dockerfile`, `src/api/{auth,users,types}.ts`, `src/auth/AuthProvider.tsx`, `src/App.tsx`, `src/features/auth/{LoginPage,ResetPasswordPage}.tsx`, new `src/features/account/TwoStepCard.tsx`, `AccountPage.tsx`, `UsersPage.tsx`, three forms for zod 4, tests.
Deployment: `docker-compose.yml`, `docker-compose.dev.yml`, new `docker/db/10-app-role.sh`, `.env.example`, `Makefile`. Docs: `installation.md`, `user-manual.md`, this file.

## Tests performed

| Test | Result |
|---|---|
| Backend suite (pytest, PostgreSQL) | 309 passed |
| Frontend suite (Vitest) + type check + production build | 78 passed; clean; builds |
| `pip-audit` (runtime + dev) / `npm audit` | 0 / 0 known vulnerabilities |
| Live authorization probe (36 cases) | 36 passed |
| Live two-step sign-in and reset-link browser test (14 checks) | 14 passed |
| Live: IP spoofing, rate limits, headers, HSTS, API docs, exposed files | all as expected (see table above) |
| Live: backup, download, restore under the least-privilege role | passed, data identical |
| Website regression (32 keyboard/mobile checks) | passed |
| Git history and build secret scan | clean |
| Container logs | no errors; no secrets |

## Remaining risks

1. **Plain HTTP by default.** On the shop LAN, passwords and tokens cross the network unencrypted. Anything beyond a trusted LAN must use HTTPS ([installation guide, section 6](installation.md)).
2. **Existing installations** keep using the superuser database role until an operator adds `APP_DB_USER`/`APP_DB_PASSWORD` and runs `make db-least-privilege` (a startup warning says so).
3. **Two-step sign-in is optional** and has no self-service recovery codes; recovery is a Super Admin reset (or, for the last Super Admin, an operator clearing the three `totp_*` columns). Authenticator secrets are stored unencrypted in the database, protected by the database role and network isolation.
4. **Rate limits are per process.** The API's limits are kept per worker (2 workers ⇒ up to 2× the configured numbers) and are not shared between servers; nginx's per-IP limits are shared within one web container. Behind another proxy, configure `set_real_ip_from`, or all clients share the proxy's limit.
5. `style-src 'unsafe-inline'` remains in the CSP (charts use inline styles). Scripts are strictly `'self'`, so injected markup cannot run code.
6. **Backups are not encrypted at rest**; keep off-site copies encrypted.
7. The database connection is unencrypted, but it never leaves the Docker network on one host; use `sslmode=require` if PostgreSQL moves to another machine.
8. **Container base images were not scanned** (no image scanner was available). Also, this sandbox could not reach the Debian package mirrors, so the API image could not be rebuilt from scratch: the patched Python packages were installed on top of the existing image for the live tests. A normal `docker compose build` on a networked machine installs the same pinned versions.
9. Major-version upgrades with no known vulnerability were not applied (for example React 19, Tailwind 4, SQLAlchemy 2.1, pandas 3) to avoid unrelated risk.
10. The demo password in `docs/demo-script.md` is public. The demo seeder refuses to run in production, but deactivate any demo accounts on a real store.

## Recommended next steps

1. Serve over HTTPS with a reverse proxy, set `COOKIE_SECURE=true`, and run `make db-least-privilege` on existing installs.
2. Make two-step sign-in mandatory for Super Admins and Store Managers, and add one-time recovery codes.
3. Add `pip-audit`, `npm audit`, an image scanner (e.g. Trivy) and a secret scanner (e.g. gitleaks) to CI, plus Dependabot/Renovate for updates.
4. Move rate-limit state to Redis if the API is ever scaled beyond one host.
5. Encrypt off-site backups; consider encrypting authenticator secrets with a key held outside the database.

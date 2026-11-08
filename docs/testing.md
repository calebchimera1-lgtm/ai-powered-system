# Testing

All tests below run in a few minutes on a laptop and were passing when this was written (end of
Phase 6): **287 backend tests** (pytest) and **77 frontend tests** (Vitest), plus the AI
evaluation scripts and a browser walk-through of each phase.

## How to run

```bash
# Backend (needs PostgreSQL; the tests create and drop their own database, inventory_test)
cd backend
pip install -r requirements.txt -r requirements-dev.txt
TEST_DATABASE_URL=postgresql+psycopg://inventory:inventory@localhost:5432/inventory_test python -m pytest

# Frontend
cd frontend
npm ci
npm test
```

or `make test` from the project root. Tesseract must be installed for the OCR tests
(`apt-get install tesseract-ocr`); it is already in the backend Docker image.

## What is tested

| Suite | Tests | What it covers |
|---|---|---|
| `backend/tests/unit` | 134 | Pure logic with no HTTP: password hashing and policy, permission matrix, weighted average cost and batch (FEFO) rules, VAT and discount pricing, every OCR stage (money and date parsing, field and line extraction, product matching, validation, skew and perspective correction, image-quality warnings) plus an OCR accuracy regression on 10 generated invoices, forecasting metrics/models/backtest/selection/replenishment maths checked by hand, anomaly baselines, rules, Isolation Forest and merging |
| `backend/tests/integration` | 152 | The real API against a real PostgreSQL database: sign-in, refresh-token rotation and reuse, rate limits, users and roles, audit log, the append-only ledger trigger, products/categories/suppliers, stock adjustments and approvals, write-offs, POS checkout (idempotency, discount limits, **two tills selling the last item at once**), returns, purchase orders and goods received, expenses and profit, invoice upload → OCR → review → approve → stock, forecasts and reorder, irregularity scan and review rules, notifications, dashboard, all 10 reports in all 3 formats with hand-checked figures and role limits, backups with a full restore round-trip and tamper detection |
| `backend/tests/scenario` | 1 | The brief's 11-step demonstration (below), end to end |
| `frontend/src/**/*.test.tsx` | 77 | Components and pages with a mocked API: sign-in and session expiry, protected routes, navigation per role, product list and form, stock adjustment, POS (scanning, quantities, totals, change, tendering), returns, invoice review (confidence highlighting, suggested product needs confirming, save then approve), forecasts and chart table view, irregularity review rules, notification bell, dashboard filters and role views, report downloads, pricing and formatting helpers |

### Types of testing required by the brief

| Required | Where |
|---|---|
| Backend unit tests | `backend/tests/unit` |
| API integration tests | `backend/tests/integration` (FastAPI TestClient, real database) |
| Frontend component tests | `frontend/src/**/*.test.tsx` (Vitest + Testing Library) |
| Database tests | `test_inventory_ledger.py` (append-only trigger, constraints, concurrency), `test_backups.py` (dump and restore), migrations run up and down in CI-style setup |
| OCR extraction tests | `tests/unit/test_ocr.py`, `tests/integration/test_invoices_api.py`, `scripts/evaluate_ocr.py` |
| Inventory calculation tests | `tests/unit/test_inventory_rules.py`, `test_pricing.py`, `test_inventory_ledger.py`, `test_procurement_finance_api.py` |
| Authentication tests | `tests/unit/test_security.py`, `tests/integration/test_auth.py`, `test_users.py` |

## The demonstration scenario (automated)

`backend/tests/scenario/test_demo_scenario.py` runs the brief's workflow through the HTTP
API and the background worker, with no shortcuts:

1. An administrator signs in.
2. The administrator registers the suppliers and products.
3. An inventory officer uploads a (synthetic) supplier invoice photo.
4. The worker reads it. The test asserts the supplier, the invoice number and every line's product and quantity.
5. The officer approves it.
6. Stock rises by exactly the invoiced quantities.
7. A cashier sells 5 units with M-Pesa.
8. Stock falls by 5.
9. The dashboard's revenue, transaction count and gross profit change by exactly that sale, and match the finance summary.
10. A forecast run predicts next week's demand for bread within the range implied by its history.
11. Twelve units adjusted out in one day, against a normal of one now and then, raise an "unexplained stock loss" alert. Managers are notified.

The brief's section 9 test scenarios are the same steps and are asserted along the way.

## Browser walk-throughs

At the end of each phase the whole Docker stack was started with fresh demo data, and a
scripted browser (Playwright, Chromium) used the app like a person would: desktop and
phone sizes, every role, checking for console errors. Screenshots from each run were
reviewed. Bugs found this way were fixed and re-tested before the phase was committed.
Examples:
- A suggested product match was accepted just by saving the form.
- A stale warning stayed on an invoice line after it was corrected.
- Report tables wrapped their numbers.

## AI evaluation

The AI components are not judged by unit tests alone. Each has an evaluation script that
computes its metrics from data with known answers:

| Component | Script | Report |
|---|---|---|
| OCR and extraction | `scripts/evaluate_ocr.py` | [ai/ocr-evaluation.md](ai/ocr-evaluation.md), method in [ai/ocr-methodology.md](ai/ocr-methodology.md) |
| Demand forecasting | `scripts/evaluate_forecasts.py` | [ai/forecast-evaluation.md](ai/forecast-evaluation.md) |
| Anomaly detection | `scripts/evaluate_anomalies.py` | [ai/anomaly-evaluation.md](ai/anomaly-evaluation.md), method for both in [ai/forecasting-and-anomalies.md](ai/forecasting-and-anomalies.md) |

All three use **synthetic** data, and keep tuning data apart from the final test data.
The reports state their limits plainly.

## Known gaps

- There is no load test. The system is designed for one store: a handful of tills and a few
  staff. The concurrency tests cover correctness under simultaneous sales, not throughput.
- The frontend tests mock the API. End-to-end behaviour in the browser is covered by the
  scripted walk-throughs above. These are run by hand at the end of each phase, not on every
  change.
- OCR, forecasting and anomaly figures come from synthetic data. Real-world accuracy is
  measured in the app once it is used: the share of invoice lines corrected, and the share of
  irregularities confirmed on review.

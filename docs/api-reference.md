# API reference

Generated from the OpenAPI specification by `python -m scripts.generate_docs`. The live, interactive version (with request and response schemas) is at `/api/docs` on a development server; the full machine-readable spec is in `api/openapi.json`.

**Conventions.** JSON over HTTPS; base path `/api/v1`. Authenticate with `POST /auth/login`, then send `Authorization: Bearer <access token>` (15 minutes) and the `X-Requested-With: XMLHttpRequest` header; the refresh token is an HttpOnly cookie used by `POST /auth/refresh`. Lists are paginated (`page`, `page_size` ≤ 100) and return `{items, total, page, page_size, pages}`. Errors are `{error: {code, message, details}}` with 401 (signed out), 403 (no permission), 404, 409 (conflict, e.g. duplicate), 422 (validation) or 429 (rate limited). Every endpoint checks the caller's permissions on the server.

104 operations.

## Anomaly detection

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/anomalies` | List Alerts |
| POST | `/api/v1/anomalies/scan` | Scan Now |
| GET | `/api/v1/anomalies/stats` | Open alerts by severity and the real-world precision of reviewed alerts. |
| GET | `/api/v1/anomalies/{alert_id}` | Get Alert |
| POST | `/api/v1/anomalies/{alert_id}/review` | Record what the investigation found. Resolving needs a note. |

## Audit

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/audit-logs` | Newest first. Dates are interpreted in the store's timezone (Africa/Nairobi). |

## Authentication

| Method | Path | What it does |
|---|---|---|
| POST | `/api/v1/auth/change-password` | Change your own password. Other devices are signed out. |
| POST | `/api/v1/auth/login` | Sign in with username (or email) and password. |
| POST | `/api/v1/auth/logout` | Logout |
| GET | `/api/v1/auth/me` | Me |
| POST | `/api/v1/auth/refresh` | Exchange the refresh cookie for a new access token (and a rotated cookie). |
| POST | `/api/v1/auth/reset-password` | Set a new password using a one-time link issued by an administrator. |
| GET | `/api/v1/auth/sessions` | Devices currently signed in to your account. |
| DELETE | `/api/v1/auth/sessions/{session_id}` | Sign out one of your other devices. |

## Backups

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/system/backups` | List Backups |
| POST | `/api/v1/system/backups` | Back Up Now |
| GET | `/api/v1/system/backups/{name}/{file}` | Download |

## Categories

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/categories` | List Categories |
| POST | `/api/v1/categories` | Create Category |
| DELETE | `/api/v1/categories/{category_id}` | Delete Category |
| PATCH | `/api/v1/categories/{category_id}` | Update Category |

## Dashboard

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/dashboard` | Defaults to the last 30 days. Sales and stock value need finance permission; |

## Finance

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/analytics/overview` | Everything the profit page needs in one request. |
| GET | `/api/v1/analytics/products` | Analytics Products |
| GET | `/api/v1/analytics/summary` | Analytics Summary |
| GET | `/api/v1/expense-categories` | Expense Categories |
| GET | `/api/v1/expenses` | List Expenses |
| POST | `/api/v1/expenses` | Create Expense |
| DELETE | `/api/v1/expenses/{expense_id}` | Delete Expense |
| PUT | `/api/v1/expenses/{expense_id}` | Update Expense |

## Forecasting

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/forecasts` | The latest forecast for every product, most urgent (earliest stock-out) first. |
| GET | `/api/v1/forecasts/products/{product_id}` | Actual sales for the last 13 weeks and the forecast with its 80% interval. |
| GET | `/api/v1/forecasts/reorder` | What to order now, grouped by each product's usual supplier. |
| POST | `/api/v1/forecasts/run` | Re-train and re-forecast in the background (takes a few seconds to a minute). |

## Invoice digitization

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/invoices` | List Invoices |
| POST | `/api/v1/invoices` | Upload a supplier invoice. It is read in the background; poll until NEEDS_REVIEW. |
| GET | `/api/v1/invoices/stats` | Counts by status and how often reviewers had to correct the OCR (real accuracy). |
| GET | `/api/v1/invoices/{invoice_id}` | Get Invoice |
| PUT | `/api/v1/invoices/{invoice_id}` | Save the reviewer's corrections. Stock is not changed until approval. |
| POST | `/api/v1/invoices/{invoice_id}/approve` | Receive the reviewed invoice into stock (creates a goods-received note). |
| GET | `/api/v1/invoices/{invoice_id}/original` | Original |
| GET | `/api/v1/invoices/{invoice_id}/pages/{page}` | Page Image |
| POST | `/api/v1/invoices/{invoice_id}/reject` | Reject |
| POST | `/api/v1/invoices/{invoice_id}/reprocess` | Read the document again (e.g. after adding the supplier or products). |

## Media

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/media/products/{name}` | Product Image |

## Notifications

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/notifications` | My Notifications |
| POST | `/api/v1/notifications/read` | Mark the given notifications (or, with no ids, all of them) as read. |
| GET | `/api/v1/notifications/unread-count` | Unread Count |

## Products

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/products` | Search by name (typo-tolerant), SKU or barcode; filter by category and stock state. |
| POST | `/api/v1/products` | Create Product |
| GET | `/api/v1/products/lookup` | Find the product for a scanned barcode or typed SKU (exact match). |
| DELETE | `/api/v1/products/{product_id}` | Permanently delete a product that has never had stock. Otherwise deactivate it. |
| GET | `/api/v1/products/{product_id}` | Get Product |
| PATCH | `/api/v1/products/{product_id}` | Update Product |
| POST | `/api/v1/products/{product_id}/barcode` | Give a product without a manufacturer barcode an internal EAN-13 (prefix 20). |
| GET | `/api/v1/products/{product_id}/barcode.svg` | Barcode Svg |
| GET | `/api/v1/products/{product_id}/batches` | Product Batches |
| DELETE | `/api/v1/products/{product_id}/image` | Delete Image |
| POST | `/api/v1/products/{product_id}/image` | Upload Image |
| GET | `/api/v1/products/{product_id}/suppliers` | Suppliers of this product with their last prices (cheapest first). |

## Purchasing

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/purchase-orders` | List Orders |
| POST | `/api/v1/purchase-orders` | Create Order |
| GET | `/api/v1/purchase-orders/{po_id}` | Get Order |
| PUT | `/api/v1/purchase-orders/{po_id}` | Update Order |
| POST | `/api/v1/purchase-orders/{po_id}/cancel` | Cancel Order |
| POST | `/api/v1/purchase-orders/{po_id}/send` | Mark the order as sent to the supplier (by phone, email or in person). |
| GET | `/api/v1/purchases` | List Received |
| POST | `/api/v1/purchases` | Record goods received: stock, average cost, batches and supplier prices update. |
| GET | `/api/v1/purchases/{purchase_id}` | Get Received |

## Reports

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/reports` | The reports this user may download. |
| GET | `/api/v1/reports/{key}` | Download |

## Roles

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/roles` | List Roles |

## Sales

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/returns` | List Returns |
| POST | `/api/v1/returns/{return_id}/approve` | Approve Return |
| POST | `/api/v1/returns/{return_id}/reject` | Reject Return |
| GET | `/api/v1/sales` | Cashiers see only their own sales. |
| POST | `/api/v1/sales` | Complete a sale: prices come from the catalogue; stock is deducted atomically. |
| GET | `/api/v1/sales/by-receipt/{receipt_number}` | By Receipt |
| GET | `/api/v1/sales/summary` | Totals by payment method, e.g. for the end-of-day cash-up. |
| GET | `/api/v1/sales/{sale_id}` | Get Sale |
| POST | `/api/v1/sales/{sale_id}/returns` | Return items from a receipt. Cashiers' returns wait for a manager's approval. |
| GET | `/api/v1/store` | Store details printed on receipts, and the cashier discount limit. |

## Stock

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/stock/adjustments` | List Adjustments |
| POST | `/api/v1/stock/adjustments` | Record a stock count or correction. Large changes wait for manager approval. |
| POST | `/api/v1/stock/adjustments/{adjustment_id}/approve` | Approve |
| POST | `/api/v1/stock/adjustments/{adjustment_id}/reject` | Reject |
| GET | `/api/v1/stock/movements` | The stock ledger, newest first. `movement_type` accepts a comma-separated list. |
| GET | `/api/v1/stock/summary` | Stock Summary |
| POST | `/api/v1/stock/write-offs` | Remove damaged or expired goods from stock (FEFO unless a batch is chosen). |

## Suppliers

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/suppliers` | List Suppliers |
| POST | `/api/v1/suppliers` | Create Supplier |
| GET | `/api/v1/suppliers/{supplier_id}` | Get Supplier |
| PATCH | `/api/v1/suppliers/{supplier_id}` | Update Supplier |
| GET | `/api/v1/suppliers/{supplier_id}/products` | Supplier Products |
| DELETE | `/api/v1/suppliers/{supplier_id}/products/{product_id}` | Unlink Product |
| PUT | `/api/v1/suppliers/{supplier_id}/products/{product_id}` | Record that this supplier sells the product (and their code / last price). |

## System

| Method | Path | What it does |
|---|---|---|
| GET | `/api/health` | Liveness/readiness probe used by Docker. |

## Users

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/users` | List Users |
| POST | `/api/v1/users` | Register a staff member. Omit `password` to get a one-time setup link instead. |
| GET | `/api/v1/users/{user_id}` | Get User |
| PATCH | `/api/v1/users/{user_id}` | Update User |
| POST | `/api/v1/users/{user_id}/reset-password` | Issue a one-time password reset link to give to the staff member. |
| POST | `/api/v1/users/{user_id}/revoke-sessions` | Sign the user out of every device. |
| POST | `/api/v1/users/{user_id}/unlock` | Unlock User |

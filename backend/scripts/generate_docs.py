"""Generate the database schema and API reference from the code, so they cannot drift.

python -m scripts.generate_docs        # writes docs/database-schema.md, docs/api-reference.md,
                                      # docs/api/openapi.json
"""

import json
from collections import defaultdict
from pathlib import Path

from sqlalchemy import CheckConstraint, UniqueConstraint

from app.main import app
from app.models import Base

DOCS = Path(__file__).resolve().parents[2] / "docs"

GROUPS = {
    "Identity and audit": [
        "users",
        "roles",
        "permissions",
        "role_permissions",
        "user_sessions",
        "password_reset_tokens",
        "audit_logs",
        "background_jobs",
    ],
    "Catalogue and suppliers": [
        "categories",
        "products",
        "product_batches",
        "suppliers",
        "supplier_products",
        "product_price_history",
    ],
    "Stock": ["stock_movements", "stock_adjustments"],
    "Sales": ["customers", "sales", "sale_items", "sale_returns", "sale_return_items"],
    "Purchasing and finance": [
        "purchase_orders",
        "purchase_order_items",
        "purchases",
        "purchase_items",
        "expense_categories",
        "expenses",
    ],
    "Invoice digitization": ["invoices", "invoice_items", "supplier_product_aliases"],
    "Forecasting, anomalies and notifications": [
        "forecast_runs",
        "forecast_products",
        "forecasts",
        "anomaly_alerts",
        "notifications",
    ],
}


def _type(col) -> str:  # type: ignore[no-untyped-def]
    t = str(col.type)
    return (
        t.replace("VARCHAR", "varchar")
        .replace("NUMERIC", "numeric")
        .replace("TIMESTAMP", "timestamp")
    )


def schema() -> str:
    tables = Base.metadata.tables
    lines = [
        "# Database schema",
        "",
        "Generated from the SQLAlchemy models by `python -m scripts.generate_docs`; the Alembic "
        "migrations in `backend/alembic/versions` create exactly these tables. PostgreSQL 16.",
        "",
        f"{len(tables)} tables. Money is `numeric(14,2)` (KES), costs `numeric(14,4)`, quantities "
        "`numeric(14,3)`; timestamps are stored with time zone (UTC) and shown in store time.",
        "",
        "## Entity relationship diagram",
        "",
        "Primary and foreign keys only; full columns are listed below.",
        "",
        "```mermaid",
        "erDiagram",
    ]
    seen = set()
    for t in tables.values():
        for fk in t.foreign_keys:
            parent, child = fk.column.table.name, t.name
            key = (parent, child, fk.parent.name)
            if key in seen or parent == child and fk.parent.name.endswith("_by_id"):
                continue
            seen.add(key)
            card = "|o--o{" if fk.parent.nullable else "||--o{"
            lines.append(f'    {parent} {card} {child} : "{fk.parent.name}"')
    lines += ["```", ""]
    grouped = {n for names in GROUPS.values() for n in names}
    groups = dict(GROUPS)
    rest = sorted(n for n in tables if n not in grouped and n != "alembic_version")
    if rest:
        groups["Other"] = rest
    for title, names in groups.items():
        present = [n for n in names if n in tables]
        if not present:
            continue
        lines += [f"## {title}", ""]
        for name in present:
            t = tables[name]
            lines += [f"### `{name}`", ""]
            if t.comment:
                lines += [t.comment, ""]
            lines += ["| Column | Type | Null | Key / default |", "|---|---|---|---|"]
            for c in t.columns:
                keys = []
                if c.primary_key:
                    keys.append("PK")
                for fk in c.foreign_keys:
                    keys.append(f"FK → `{fk.column.table.name}.{fk.column.name}`")
                if c.unique:
                    keys.append("unique")
                if c.server_default is not None:
                    keys.append("default " + str(getattr(c.server_default, "arg", "")).strip("'"))
                lines.append(
                    f"| `{c.name}` | {_type(c)} | {'yes' if c.nullable else 'no'} | "
                    f"{', '.join(keys)} |"
                )
            cons = []
            for con in t.constraints:
                if isinstance(con, CheckConstraint):
                    cons.append(f"check `{con.name}`: `{con.sqltext}`")
                elif isinstance(con, UniqueConstraint) and len(con.columns) > 1:
                    cons.append("unique (" + ", ".join(c.name for c in con.columns) + ")")
            for ix in t.indexes:
                where = ix.dialect_options["postgresql"].get("where")
                cols = ", ".join(str(getattr(e, "name", e)) for e in ix.expressions)
                cons.append(
                    f"{'unique ' if ix.unique else ''}index `{ix.name}` ({cols})"
                    + (f" where `{where}`" if where is not None else "")
                )
            if cons:
                lines += ["", "Constraints and indexes: " + "; ".join(cons) + "."]
            lines.append("")
    lines += [
        "## Rules enforced in the database",
        "",
        "- `stock_movements` is append-only: a trigger rejects UPDATE and DELETE, so the ledger "
        "cannot be rewritten (corrections are new movements).",
        "- Check constraints keep quantities, prices and statuses valid even if application code "
        "had a bug; partial unique indexes stop the same supplier invoice being received twice.",
        "- Document numbers (receipts, returns, orders, deliveries) come from PostgreSQL "
        "sequences, so they stay unique when several tills work at once. A sequence can skip a "
        "number if a transaction is rolled back, so numbers are unique but not guaranteed "
        "consecutive.",
        "",
    ]
    return "\n".join(lines)


def api_reference(spec: dict) -> str:
    by_tag: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            tag = (op.get("tags") or ["Other"])[0]
            summary = op.get("summary") or ""
            desc = (op.get("description") or "").strip().split("\n")[0]
            by_tag[tag].append((method.upper(), path, desc or summary))
    lines = [
        "# API reference",
        "",
        "Generated from the OpenAPI specification by `python -m scripts.generate_docs`. The live, "
        "interactive version (with request and response schemas) is at `/api/docs` on a "
        "development server; the full machine-readable spec is in `api/openapi.json`.",
        "",
        "**Conventions.** JSON over HTTPS; base path `/api/v1`. Authenticate with "
        "`POST /auth/login`, then send `Authorization: Bearer <access token>` (15 minutes) and the "
        "`X-Requested-With: XMLHttpRequest` header; the refresh token is an HttpOnly cookie used "
        "by `POST /auth/refresh`. Lists are paginated (`page`, `page_size` ≤ 100) and return "
        "`{items, total, page, page_size, pages}`. Errors are `{error: {code, message, details}}` "
        "with 401 (signed out), 403 (no permission), 404, 409 (conflict, e.g. duplicate), "
        "422 (validation) or 429 (rate limited). Every endpoint checks the caller's permissions "
        "on the server.",
        "",
        f"{sum(len(v) for v in by_tag.values())} operations.",
        "",
    ]
    for tag in sorted(by_tag):
        lines += [f"## {tag}", "", "| Method | Path | What it does |", "|---|---|---|"]
        for method, path, desc in sorted(by_tag[tag], key=lambda x: (x[1], x[0])):
            lines.append(f"| {method} | `{path}` | {desc.replace('|', '/')} |")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    spec = app.openapi()
    (DOCS / "api").mkdir(parents=True, exist_ok=True)
    (DOCS / "api" / "openapi.json").write_text(json.dumps(spec, indent=1))
    (DOCS / "api-reference.md").write_text(api_reference(spec))
    (DOCS / "database-schema.md").write_text(schema())
    print("Wrote docs/database-schema.md, docs/api-reference.md, docs/api/openapi.json")


if __name__ == "__main__":
    main()

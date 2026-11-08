"""The ten downloadable reports. Each builder returns a writer-neutral `Report`.

Who may export what (see app/core/permissions.py):
* reports:all        every report (Store Manager, Super Admin)
* reports:inventory  stock, purchasing, supplier and forecast reports (Inventory Officer)
* reports:own_sales  the daily sales report, limited to the cashier's own sales, no costs
The irregularities report also needs anomalies:read; staff-related alerts appear only for
reviewers.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.ai.anomaly.detector import KIND_LABELS
from app.core.config import get_settings
from app.core.exceptions import NotFoundError, PermissionDenied, ValidationFailed
from app.core.permissions import P
from app.models import (
    AnomalyAlert,
    Category,
    Forecast,
    Product,
    ProductBatch,
    ProductForecast,
    Purchase,
    PurchaseOrder,
    Sale,
    SaleItem,
    SaleReturn,
    SaleReturnItem,
    StockMovement,
    Supplier,
    User,
)
from app.reports.writers import Column, Report
from app.services import finance_service, forecast_service

ZERO = Decimal(0)
CENT = Decimal("0.01")


def _m(v: Any) -> Decimal:
    return Decimal(v or 0).quantize(CENT, ROUND_HALF_UP)


def _tz() -> ZoneInfo:
    return ZoneInfo(get_settings().store_timezone)


def _bounds(d1: date, d2: date) -> tuple[datetime, datetime]:
    return datetime.combine(d1, time.min, _tz()), datetime.combine(
        d2 + timedelta(days=1), time.min, _tz()
    )


def _day(col: Any) -> Any:
    return cast(func.timezone(get_settings().store_timezone, col), Date)


def _period(d1: date, d2: date) -> str:
    return f"{d1:%d %b %Y}" if d1 == d2 else f"{d1:%d %b %Y} to {d2:%d %b %Y}"


def _local(dt: datetime) -> datetime:
    return dt.astimezone(_tz())


@dataclass
class Ctx:
    user: User
    d1: date
    d2: date
    category_id: int | None
    category_name: str | None

    def can(self, p: P) -> bool:
        return p.value in self.user.permission_codes

    def subtitle(self, period: bool = True, extra: str = "") -> str:
        parts = (
            [_period(self.d1, self.d2)]
            if period
            else [f"As at {datetime.now(_tz()):%d %b %Y %H:%M}"]
        )
        if self.category_name:
            parts.append(f"Category: {self.category_name}")
        if extra:
            parts.append(extra)
        return " · ".join(parts)

    def product_ok(self, p: Product) -> bool:
        return self.category_id is None or p.category_id == self.category_id


# --- 1. Inventory valuation -------------------------------------------------------------


def inventory_valuation(db: Session, c: Ctx) -> Report:
    cats = dict(db.execute(select(Category.id, Category.name)).all())
    rows = []
    for p in db.scalars(select(Product).where(Product.is_active).order_by(Product.name)):
        if not c.product_ok(p):
            continue
        on_hand = max(p.quantity_on_hand, ZERO)
        rows.append(
            {
                "name": p.name,
                "sku": p.sku,
                "category": cats.get(p.category_id, ""),
                "on_hand": p.quantity_on_hand,
                "unit": p.unit_of_measure,
                "avg_cost": p.avg_cost,
                "value": _m(on_hand * p.avg_cost),
                "price": p.selling_price,
                "retail": _m(on_hand * p.selling_price),
            }
        )
    total_cost = sum((r["value"] for r in rows), ZERO)
    total_retail = sum((r["retail"] for r in rows), ZERO)
    return Report(
        title="Inventory valuation",
        subtitle=c.subtitle(period=False),
        columns=[
            Column("name", "Product"),
            Column("sku", "SKU"),
            Column("category", "Category"),
            Column("on_hand", "On hand", "qty"),
            Column("unit", "Unit"),
            Column("avg_cost", "Average cost", "money"),
            Column("value", "Value at cost", "money"),
            Column("price", "Selling price", "money"),
            Column("retail", "Value at selling price", "money"),
        ],
        rows=rows,
        totals={"name": "Total", "value": total_cost, "retail": total_retail},
        summary=[
            ("Products", str(len(rows))),
            ("Stock value at cost (KES)", f"{total_cost:,.2f}"),
            ("Stock value at selling price (KES)", f"{total_retail:,.2f}"),
        ],
        notes=[
            "Cost is the weighted average cost of the stock on hand (excl. VAT). Selling prices "
            "include VAT. Negative stock (if any) is counted as zero in the values."
        ],
    )


# --- 2. Daily sales ----------------------------------------------------------------------


def daily_sales(db: Session, c: Ctx) -> Report:
    own = not c.can(P.REPORTS_ALL)  # cashiers: their own sales, no costs
    show_profit = c.can(P.FINANCE_READ) and not own
    s, e = _bounds(c.d1, c.d2)
    day = _day(Sale.sold_at)
    q = (
        select(
            day,
            func.count(func.distinct(Sale.id)),
            func.sum(SaleItem.quantity),
            func.sum(SaleItem.line_total),
            func.sum(SaleItem.tax_amount),
            func.sum(SaleItem.discount_amount),
            func.sum(SaleItem.quantity * SaleItem.unit_cost),
        )
        .join(SaleItem, SaleItem.sale_id == Sale.id)
        .where(Sale.sold_at >= s, Sale.sold_at < e)
        .group_by(day)
        .order_by(day)
    )
    if own:
        q = q.where(Sale.cashier_id == c.user.id)
    if c.category_id is not None:
        q = q.join(Product, Product.id == SaleItem.product_id).where(
            Product.category_id == c.category_id
        )
    rday = _day(SaleReturn.decided_at)
    rq = (
        select(rday, func.sum(SaleReturnItem.refund_amount))
        .join(SaleReturnItem, SaleReturnItem.return_id == SaleReturn.id)
        .join(SaleItem, SaleItem.id == SaleReturnItem.sale_item_id)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(
            SaleReturn.status == "APPROVED", SaleReturn.decided_at >= s, SaleReturn.decided_at < e
        )
        .group_by(rday)
    )
    if own:
        rq = rq.where(Sale.cashier_id == c.user.id)
    if c.category_id is not None:
        rq = rq.join(Product, Product.id == SaleItem.product_id).where(
            Product.category_id == c.category_id
        )
    refunds = dict(db.execute(rq).all())
    rows = []
    for d, n, items, gross, vat, disc, cost in db.execute(q).all():
        net = _m(gross) - _m(vat)
        row = {
            "day": d,
            "sales": n,
            "items": items,
            "gross": _m(gross),
            "vat": _m(vat),
            "discounts": _m(disc),
            "refunds": _m(refunds.get(d)),
            "net": net,
        }
        if show_profit:
            row["profit"] = net - _m(cost)
        rows.append(row)
    cols = [
        Column("day", "Day", "date"),
        Column("sales", "Sales", "int"),
        Column("items", "Items", "qty"),
        Column("gross", "Sales incl. VAT", "money"),
        Column("vat", "VAT", "money"),
        Column("discounts", "Discounts", "money"),
        Column("refunds", "Refunds incl. VAT", "money"),
        Column("net", "Sales excl. VAT", "money"),
    ]
    if show_profit:
        cols.append(Column("profit", "Gross profit", "money"))
    totals: dict[str, Any] = {"day": "Total"}
    for k in ("sales", "items", "gross", "vat", "discounts", "refunds", "net", "profit"):
        if rows and k in rows[0]:
            totals[k] = sum((r[k] for r in rows), ZERO if k not in ("sales",) else 0)
    notes = (
        ["Gross profit is before refunds, write-offs and expenses; see the profitability report."]
        if show_profit
        else []
    )
    return Report(
        title="Daily sales" + (f" — {c.user.full_name}" if own else ""),
        subtitle=c.subtitle(extra="own sales only" if own else ""),
        columns=cols,
        rows=rows,
        totals=totals if rows else None,
        notes=notes,
    )


# --- 3. Monthly sales ----------------------------------------------------------------------


def monthly_sales(db: Session, c: Ctx) -> Report:
    rows = []
    month = c.d1.replace(day=1)
    while month <= c.d2:
        nxt = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
        a, b = max(month, c.d1), min(nxt - timedelta(days=1), c.d2)
        if c.category_id is None:
            f = finance_service.summary(db, a, b)
            rows.append(
                {
                    "month": f"{month:%b %Y}",
                    "sales": f["transactions"],
                    "items": f["items_sold"],
                    "gross": f["sales_gross"],
                    "refunds": f["refunds_gross"],
                    "revenue": f["revenue"],
                    "profit": f["gross_profit"],
                    "margin": f["gross_margin_percent"],
                }
            )
        else:
            cat = set(db.scalars(select(Product.id).where(Product.category_id == c.category_id)))
            prods = [r for r in finance_service.by_product(db, a, b) if r["product_id"] in cat]
            rev = sum((r["revenue"] for r in prods), ZERO)
            gp = sum((r["gross_profit"] for r in prods), ZERO)
            rows.append(
                {
                    "month": f"{month:%b %Y}",
                    "items": sum((r["quantity"] for r in prods), ZERO),
                    "revenue": _m(rev),
                    "profit": _m(gp),
                    "margin": _m(gp / rev * 100) if rev else None,
                }
            )
        month = nxt
    cols = [Column("month", "Month")]
    if c.category_id is None:
        cols += [
            Column("sales", "Sales", "int"),
            Column("items", "Items (net)", "qty"),
            Column("gross", "Sales incl. VAT", "money"),
            Column("refunds", "Refunds incl. VAT", "money"),
        ]
    else:
        cols += [Column("items", "Items (net)", "qty")]
    cols += [
        Column("revenue", "Revenue excl. VAT", "money"),
        Column("profit", "Gross profit", "money"),
        Column("margin", "Margin", "percent"),
    ]
    rev = sum((r["revenue"] for r in rows), ZERO)
    gp = sum((r["profit"] for r in rows), ZERO)
    totals = {
        "month": "Total",
        "revenue": rev,
        "profit": gp,
        "margin": _m(gp / rev * 100) if rev else None,
    }
    for k in ("sales", "gross", "refunds", "items"):
        if rows and k in rows[0]:
            totals[k] = sum((r[k] for r in rows), 0 if k == "sales" else ZERO)
    return Report(
        title="Monthly sales",
        subtitle=c.subtitle(),
        columns=cols,
        rows=rows,
        totals=totals,
        notes=[
            "Revenue is net of VAT and of refunds. A partial first or last month covers only "
            "the days in the chosen period."
        ],
    )


# --- 4. Profitability -------------------------------------------------------------------------


def profitability(db: Session, c: Ctx) -> Report:
    rows = [
        r
        for r in finance_service.by_product(db, c.d1, c.d2)
        if c.category_id is None
        or r["product_id"]
        in set(db.scalars(select(Product.id).where(Product.category_id == c.category_id)))
    ]
    rows.sort(key=lambda r: r["gross_profit"], reverse=True)
    rev = sum((r["revenue"] for r in rows), ZERO)
    cogs = sum((r["cost_of_goods_sold"] for r in rows), ZERO)
    summary: list[tuple[str, str]] = []
    notes = [
        "Revenue excludes VAT and is net of refunds; cost of goods sold uses the weighted "
        "average cost at the moment of each sale."
    ]
    if c.category_id is None:
        f = finance_service.summary(db, c.d1, c.d2)
        summary = [
            ("Revenue (excl. VAT)", f"KES {f['revenue']:,.2f}"),
            ("Cost of goods sold", f"KES {f['cost_of_goods_sold']:,.2f}"),
            ("Gross profit", f"KES {f['gross_profit']:,.2f}"),
            ("Stock losses (write-offs, damaged returns)", f"KES {f['stock_losses']:,.2f}"),
            ("Net stock adjustments", f"KES {f['net_adjustments']:,.2f}"),
            ("Operating expenses", f"KES {f['operating_expenses']:,.2f}"),
            ("Net profit (estimate)", f"KES {f['net_profit_estimate']:,.2f}"),
        ]
        notes.append(
            "Net profit is an estimate: gross profit minus stock losses, plus or minus "
            "adjustments, minus recorded expenses. It is not an accounting statement."
        )
    return Report(
        title="Profitability",
        subtitle=c.subtitle(),
        columns=[
            Column("name", "Product"),
            Column("category", "Category"),
            Column("quantity", "Units (net)", "qty"),
            Column("revenue", "Revenue excl. VAT", "money"),
            Column("cost_of_goods_sold", "Cost of goods", "money"),
            Column("gross_profit", "Gross profit", "money"),
            Column("margin_percent", "Margin", "percent"),
        ],
        rows=rows,
        summary=summary,
        notes=notes,
        totals={
            "name": "Total",
            "revenue": rev,
            "cost_of_goods_sold": cogs,
            "gross_profit": rev - cogs,
            "margin_percent": _m((rev - cogs) / rev * 100) if rev else None,
        },
    )


# --- 5. Purchase history ----------------------------------------------------------------------


def purchase_history(db: Session, c: Ctx) -> Report:
    s, e = _bounds(c.d1, c.d2)
    rows = []
    for pu in db.scalars(
        select(Purchase)
        .where(Purchase.received_at >= s, Purchase.received_at < e)
        .order_by(Purchase.received_at)
    ).unique():
        items = [i for i in pu.items if c.product_ok(i.product)]
        if not items:
            continue
        sub = sum((i.quantity * i.unit_cost for i in items), ZERO) if c.category_id else pu.subtotal
        rows.append(
            {
                "when": _local(pu.received_at),
                "grn": pu.grn_number,
                "supplier": pu.supplier.name,
                "invoice": pu.supplier_invoice_number or "",
                "po": pu.purchase_order.po_number if pu.purchase_order else "",
                "source": {"INVOICE": "Scanned invoice", "MANUAL": "Entered"}.get(
                    pu.source, pu.source.title()
                ),
                "lines": len(items),
                "subtotal": _m(sub),
                "total": pu.grand_total if c.category_id is None else None,
            }
        )
    return Report(
        title="Purchase history",
        subtitle=c.subtitle(),
        landscape=True,
        columns=[
            Column("when", "Received", "datetime"),
            Column("grn", "Delivery"),
            Column("supplier", "Supplier"),
            Column("invoice", "Supplier invoice"),
            Column("po", "Purchase order"),
            Column("source", "Recorded from"),
            Column("lines", "Lines", "int"),
            Column("subtotal", "Cost excl. VAT", "money"),
            Column("total", "Total incl. VAT", "money"),
        ],
        rows=rows,
        totals={
            "when": "Total",
            "lines": sum(r["lines"] for r in rows),
            "subtotal": sum((r["subtotal"] for r in rows), ZERO),
            "total": sum((r["total"] or ZERO for r in rows), ZERO)
            if c.category_id is None
            else None,
        },
        notes=[
            "With a category filter, only that category's lines are counted and VAT totals "
            "are omitted."
        ]
        if c.category_id
        else [],
    )


# --- 6. Supplier performance -------------------------------------------------------------------


def supplier_performance(db: Session, c: Ctx) -> Report:
    s, e = _bounds(c.d1, c.d2)
    threshold = get_settings().price_change_alert_percent
    rows = []
    for sup in db.scalars(select(Supplier).order_by(Supplier.name)):
        purchases = (
            db.scalars(
                select(Purchase).where(
                    Purchase.supplier_id == sup.id,
                    Purchase.received_at >= s,
                    Purchase.received_at < e,
                )
            )
            .unique()
            .all()
        )
        orders = (
            db.scalars(
                select(PurchaseOrder).where(
                    PurchaseOrder.supplier_id == sup.id,
                    PurchaseOrder.order_date >= c.d1,
                    PurchaseOrder.order_date <= c.d2,
                    PurchaseOrder.status != "CANCELLED",
                )
            )
            .unique()
            .all()
        )
        if not purchases and not orders:
            continue
        lines = [i for p in purchases for i in p.items if c.product_ok(i.product)]
        changes = [
            i
            for i in lines
            if i.previous_unit_cost
            and abs((i.unit_cost - i.previous_unit_cost) / i.previous_unit_cost * 100) >= threshold
        ]
        on_time = late = 0
        ordered = received = ZERO
        lead_days: list[int] = []
        for po in orders:
            items = [i for i in po.items if c.product_ok(i.product)]
            ordered += sum((i.quantity_ordered for i in items), ZERO)
            received += sum((min(i.quantity_received, i.quantity_ordered) for i in items), ZERO)
            first = db.scalar(
                select(func.min(Purchase.received_at)).where(Purchase.purchase_order_id == po.id)
            )
            if first is not None:
                got = _local(first).date()
                lead_days.append((got - po.order_date).days)
                if po.expected_date:
                    on_time += got <= po.expected_date
                    late += got > po.expected_date
        rows.append(
            {
                "supplier": sup.name,
                "deliveries": len(purchases),
                "spend": _m(sum((i.quantity * i.unit_cost for i in lines), ZERO)),
                "orders": len(orders),
                "fill_rate": _m(received / ordered * 100) if ordered else None,
                "on_time": _m(Decimal(on_time) / (on_time + late) * 100)
                if on_time + late
                else None,
                "lead_time": round(sum(lead_days) / len(lead_days), 1) if lead_days else None,
                "price_changes": len(changes),
            }
        )
    return Report(
        title="Supplier performance",
        subtitle=c.subtitle(),
        landscape=True,
        columns=[
            Column("supplier", "Supplier"),
            Column("deliveries", "Deliveries", "int"),
            Column("spend", "Spend excl. VAT", "money"),
            Column("orders", "Purchase orders", "int"),
            Column("fill_rate", "Fill rate", "percent"),
            Column("on_time", "On time", "percent"),
            Column("lead_time", "Avg days to deliver", "qty"),
            Column("price_changes", f"Price changes ≥{threshold}%", "int"),
        ],
        rows=rows,
        totals={
            "supplier": "Total",
            "deliveries": sum(r["deliveries"] for r in rows),
            "spend": sum((r["spend"] for r in rows), ZERO),
            "orders": sum(r["orders"] for r in rows),
            "price_changes": sum(r["price_changes"] for r in rows),
        },
        notes=[
            "Fill rate: share of the quantities ordered on purchase orders that has been received. "
            "On time: first delivery on or before the expected date (orders with an expected date "
            "only). Days to deliver: order date to first delivery. Deliveries without a purchase "
            "order count towards spend and price changes only."
        ],
    )


# --- 7. Stock movement summary ------------------------------------------------------------------

MOVE_COLS = [
    ("PURCHASE_IN", "purchased"),
    ("RETURN_IN", "returned_in"),
    ("ADJUSTMENT_IN", "adjusted_in"),
    ("SALE_OUT", "sold"),
    ("ADJUSTMENT_OUT", "adjusted_out"),
    ("DAMAGED", "damaged"),
    ("EXPIRED", "expired"),
    ("RETURN_TO_SUPPLIER", "to_supplier"),
]


def stock_movements(db: Session, c: Ctx) -> Report:
    s, e = _bounds(c.d1, c.d2)
    by = {}
    for pid, mtype, q in db.execute(
        select(
            StockMovement.product_id, StockMovement.movement_type, func.sum(StockMovement.quantity)
        )
        .where(StockMovement.created_at >= s, StockMovement.created_at < e)
        .group_by(StockMovement.product_id, StockMovement.movement_type)
    ):
        by.setdefault(pid, {})[mtype] = q
    opening = dict(
        db.execute(
            select(StockMovement.product_id, func.sum(StockMovement.quantity))
            .where(StockMovement.created_at < s)
            .group_by(StockMovement.product_id)
        ).all()
    )
    rows = []
    for p in db.scalars(select(Product).where(Product.is_active).order_by(Product.name)):
        if not c.product_ok(p):
            continue
        m = by.get(p.id, {})
        row: dict[str, Any] = {
            "name": p.name,
            "unit": p.unit_of_measure,
            "opening": opening.get(p.id, ZERO),
        }
        for t, k in MOVE_COLS:
            v = m.get(t, ZERO)
            row[k] = -v if v < 0 else v
        row["closing"] = row["opening"] + sum((m.get(t, ZERO) for t, _ in MOVE_COLS), ZERO)
        rows.append(row)
    labels = {
        "purchased": "Received",
        "returned_in": "Customer returns",
        "adjusted_in": "Adjusted in",
        "sold": "Sold",
        "adjusted_out": "Adjusted out",
        "damaged": "Damaged",
        "expired": "Expired",
        "to_supplier": "To supplier",
    }
    return Report(
        title="Stock movement summary",
        subtitle=c.subtitle(),
        landscape=True,
        columns=[Column("name", "Product"), Column("opening", "Opening", "qty")]
        + [Column(k, labels[k], "qty") for _, k in MOVE_COLS]
        + [Column("closing", "Closing", "qty")],
        rows=rows,
        notes=[
            "Opening and closing balances come from the append-only stock ledger at the start and "
            "end of the period. Every individual movement is listed under Stock movements in "
            "the app."
        ],
    )


# --- 8. Expired and damaged products ------------------------------------------------------------


def expired_products(db: Session, c: Ctx) -> Report:
    s, e = _bounds(c.d1, c.d2)
    rows = []
    for mv in db.scalars(
        select(StockMovement)
        .where(
            StockMovement.movement_type.in_(["EXPIRED", "DAMAGED"]),
            StockMovement.created_at >= s,
            StockMovement.created_at < e,
        )
        .order_by(StockMovement.created_at)
    ).unique():
        p = db.get(Product, mv.product_id)
        if p is None or not c.product_ok(p):
            continue
        batch = db.get(ProductBatch, mv.batch_id) if mv.batch_id else None
        rows.append(
            {
                "when": _local(mv.created_at),
                "name": p.name,
                "kind": "Expired" if mv.movement_type == "EXPIRED" else "Damaged",
                "batch": batch.batch_number if batch and batch.batch_number else "",
                "expiry": batch.expiry_date if batch else None,
                "quantity": -mv.quantity,
                "value": _m(-mv.quantity * mv.unit_cost),
                "by": mv.user.full_name if mv.user else "",
                "reason": mv.reason or "",
            }
        )
    today = datetime.now(_tz()).date()
    still = db.execute(
        select(
            Product.name,
            ProductBatch.batch_number,
            ProductBatch.expiry_date,
            ProductBatch.quantity_remaining,
            Product.avg_cost,
            Product.category_id,
        )
        .join(Product, Product.id == ProductBatch.product_id)
        .where(ProductBatch.quantity_remaining > 0, ProductBatch.expiry_date < today)
    ).all()
    still = [r for r in still if c.category_id is None or r[5] == c.category_id]
    notes = []
    if still:
        notes.append(
            "Expired batches still in stock (write them off): "
            + "; ".join(
                f"{r[0]} batch {r[1] or '-'} expired {r[2]:%d %b}, {r[3].normalize():f} left"
                for r in still
            )
        )
    return Report(
        title="Expired and damaged stock",
        subtitle=c.subtitle(),
        landscape=True,
        columns=[
            Column("when", "Written off", "datetime"),
            Column("name", "Product"),
            Column("kind", "Type"),
            Column("batch", "Batch"),
            Column("expiry", "Expiry date", "date"),
            Column("quantity", "Quantity", "qty"),
            Column("value", "Cost value", "money"),
            Column("by", "By"),
            Column("reason", "Reason"),
        ],
        rows=rows,
        totals={
            "when": "Total",
            "quantity": sum((r["quantity"] for r in rows), ZERO),
            "value": sum((r["value"] for r in rows), ZERO),
        },
        summary=[
            ("Write-offs", str(len(rows))),
            ("Cost of stock lost (KES)", f"{sum((r['value'] for r in rows), ZERO):,.2f}"),
        ],
        notes=notes,
    )


# --- 9. Inventory irregularities -----------------------------------------------------------------


def irregularities(db: Session, c: Ctx) -> Report:
    q = select(AnomalyAlert).where(
        AnomalyAlert.period_start <= c.d2, AnomalyAlert.period_end >= c.d1
    )
    if not c.can(P.ANOMALIES_REVIEW):
        q = q.where(AnomalyAlert.entity_type == "product")
    status = {
        "OPEN": "Open",
        "INVESTIGATING": "Investigating",
        "RESOLVED_ISSUE_FOUND": "Issue found",
        "RESOLVED_NO_ISSUE": "No issue",
    }
    rows = []
    for a in db.scalars(q.order_by(AnomalyAlert.period_start)).unique():
        if a.product is not None and not c.product_ok(a.product):
            continue
        if c.category_id is not None and a.product is None:
            continue
        rows.append(
            {
                "period": a.period_start
                if a.period_start == a.period_end
                else f"{a.period_start:%d %b} – {a.period_end:%d %b %Y}",
                "subject": a.product.name
                if a.product
                else (a.subject_user.full_name if a.subject_user else ""),
                "kind": KIND_LABELS.get(a.kind, a.kind),
                "severity": a.severity.title(),
                "value": a.value_kes,
                "detector": {"RULE": "Rule", "ISOLATION_FOREST": "Pattern model", "BOTH": "Both"}[
                    a.detector
                ],
                "status": status.get(a.status, a.status),
                "explanation": a.explanation,
                "review": a.review_notes or "",
            }
        )
    found = sum(r["status"] == "Issue found" for r in rows)
    none_ = sum(r["status"] == "No issue" for r in rows)
    return Report(
        title="Inventory irregularities",
        subtitle=c.subtitle(),
        landscape=True,
        columns=[
            Column("period", "Period", "date"),
            Column("subject", "Product / staff"),
            Column("kind", "Irregularity"),
            Column("severity", "Severity"),
            Column("value", "Value (KES)", "money"),
            Column("detector", "Found by"),
            Column("status", "Status"),
            Column("explanation", "Details"),
            Column("review", "Review notes"),
        ],
        rows=rows,
        summary=[
            ("Alerts", str(len(rows))),
            ("Reviewed: issue found / no issue", f"{found} / {none_}"),
        ],
        notes=[
            "Irregularities are prompts to investigate, not findings of wrongdoing. They are "
            "found by comparing each day with the same product's or person's normal over the "
            "previous 90 days."
        ],
    )


# --- 10. Demand forecast --------------------------------------------------------------------------


def demand_forecast(db: Session, c: Ctx) -> Report:
    run = forecast_service.latest_run(db)
    if run is None:
        raise ValidationFailed("No forecast has been made yet. Update the forecast first.")
    totals = {}
    first_week = (Forecast.forecast_date < run.history_end + timedelta(days=8)).label("week")
    for pid, k, v in db.execute(
        select(Forecast.product_id, first_week, func.sum(Forecast.predicted_qty))
        .where(Forecast.run_id == run.id)
        .group_by(Forecast.product_id, "week")
    ):
        totals[(pid, bool(k))] = v
    rows = []
    for pf in db.scalars(select(ProductForecast).where(ProductForecast.run_id == run.id)).unique():
        if not c.product_ok(pf.product):
            continue
        scores = {s["model"]: s for s in pf.scores or []}
        week = totals.get((pf.product_id, True), 0) or 0
        rows.append(
            {
                "name": pf.product.name,
                "model": forecast_service.MODEL_LABELS.get(pf.model_name, pf.model_name),
                "next7": round(week, 1),
                "next28": round(week + (totals.get((pf.product_id, False), 0) or 0), 1),
                "on_hand": pf.on_hand,
                "stockout": pf.stockout_date,
                "rop": round(pf.reorder_point, 1),
                "order": pf.suggested_quantity if pf.should_order else None,
                "mase": (scores.get(pf.model_name) or {}).get("mase"),
                "confidence": "Low" if pf.low_confidence else "Normal",
            }
        )
    rows.sort(key=lambda r: (r["stockout"] is None, r["stockout"] or date.max, r["name"]))
    return Report(
        title="Demand forecast",
        landscape=True,
        subtitle=f"Forecast made {_local(run.finished_at or run.started_at):%d %b %Y %H:%M} "
        f"from sales "
        f"{run.history_start:%d %b %Y} to {run.history_end:%d %b %Y}"
        + (f" · Category: {c.category_name}" if c.category_name else ""),
        columns=[
            Column("name", "Product"),
            Column("model", "Model"),
            Column("next7", "Next 7 days", "qty"),
            Column("next28", "Next 28 days", "qty"),
            Column("on_hand", "On hand", "qty"),
            Column("stockout", "Expected stock-out", "date"),
            Column("rop", "Reorder point", "qty"),
            Column("order", "Suggested order", "qty"),
            Column("mase", "Backtest MASE", "qty"),
            Column("confidence", "Confidence"),
        ],
        rows=rows,
        notes=[
            "Each product uses the model that forecast its own past weeks best (rolling-origin "
            "backtest). MASE below 1 means better than 'same weekday last week'. Forecasts are "
            "estimates with an 80% range shown in the app; plan with that uncertainty in mind."
        ],
    )


# --- Registry ------------------------------------------------------------------------------------

Builder = Callable[[Session, Ctx], Report]


@dataclass(frozen=True)
class ReportType:
    key: str
    title: str
    description: str
    builder: Builder
    access: str  # "all" | "inventory" | "own_sales"
    uses_period: bool = True
    extra_perm: P | None = None


REPORT_TYPES = [
    ReportType(
        "inventory-valuation",
        "Inventory valuation",
        "Stock on hand and its value at cost and at selling price, now.",
        inventory_valuation,
        "inventory",
        uses_period=False,
    ),
    ReportType(
        "daily-sales",
        "Daily sales",
        "Sales, VAT, discounts and refunds for each day.",
        daily_sales,
        "own_sales",
    ),
    ReportType(
        "monthly-sales", "Monthly sales", "Revenue and gross profit by month.", monthly_sales, "all"
    ),
    ReportType(
        "profitability",
        "Profitability",
        "Revenue, cost and margin by product, with the net profit estimate.",
        profitability,
        "all",
    ),
    ReportType(
        "purchase-history",
        "Purchase history",
        "Every delivery received, with supplier invoice and order.",
        purchase_history,
        "inventory",
    ),
    ReportType(
        "supplier-performance",
        "Supplier performance",
        "Spend, fill rate, on-time delivery and price changes per supplier.",
        supplier_performance,
        "inventory",
    ),
    ReportType(
        "stock-movements",
        "Stock movement summary",
        "Opening stock, everything in and out, and closing stock per product.",
        stock_movements,
        "inventory",
    ),
    ReportType(
        "expired-products",
        "Expired and damaged stock",
        "Write-offs with batches, quantities and cost.",
        expired_products,
        "inventory",
    ),
    ReportType(
        "irregularities",
        "Inventory irregularities",
        "Irregularities found in the period and how they were reviewed.",
        irregularities,
        "all",
        extra_perm=P.ANOMALIES_READ,
    ),
    ReportType(
        "demand-forecast",
        "Demand forecast",
        "The latest forecast, stock-out dates and suggested orders.",
        demand_forecast,
        "inventory",
        uses_period=False,
        extra_perm=P.FORECASTS_READ,
    ),
]
BY_KEY = {r.key: r for r in REPORT_TYPES}


def allowed(user: User, rt: ReportType) -> bool:
    codes = user.permission_codes
    if rt.extra_perm and rt.extra_perm.value not in codes:
        return False
    if P.REPORTS_ALL.value in codes:
        return True
    if rt.access == "inventory":
        return P.REPORTS_INVENTORY.value in codes
    if rt.access == "own_sales":
        return P.REPORTS_OWN_SALES.value in codes
    return False


def available(user: User) -> list[ReportType]:
    return [r for r in REPORT_TYPES if allowed(user, r)]


def build(db: Session, user: User, key: str, d1: date, d2: date, category_id: int | None) -> Report:
    rt = BY_KEY.get(key)
    if rt is None:
        raise NotFoundError("Unknown report")
    if not allowed(user, rt):
        raise PermissionDenied("You do not have permission for this report.")
    if d2 < d1:
        raise ValidationFailed("The end date is before the start date")
    if (d2 - d1).days > 366:
        raise ValidationFailed("Choose a period of at most a year")
    name = None
    if category_id is not None:
        cat = db.get(Category, category_id)
        if cat is None:
            raise ValidationFailed("Category not found")
        name = cat.name
    return rt.builder(db, Ctx(user=user, d1=d1, d2=d2, category_id=category_id, category_name=name))

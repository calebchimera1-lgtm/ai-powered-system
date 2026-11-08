"""Management dashboard figures, for a date range and optionally one category.

Inventory figures (product counts, stock value, low stock, expiry) are as of now. Sales
figures cover the chosen period; "today" and "this month" are always shown for orientation.
Money figures are only returned to users who may see finance (the API enforces it).
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date, and_, cast, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ValidationFailed
from app.models import (
    AnomalyAlert,
    Category,
    Invoice,
    Product,
    ProductBatch,
    ProductForecast,
    PurchaseOrder,
    Sale,
    SaleItem,
    SaleReturn,
    StockAdjustment,
)
from app.services import finance_service, forecast_service

CENT = Decimal("0.01")


def _tz() -> ZoneInfo:
    return ZoneInfo(get_settings().store_timezone)


def today() -> date:
    return datetime.now(_tz()).date()


def _bounds(d1: date, d2: date) -> tuple[datetime, datetime]:
    return datetime.combine(d1, time.min, _tz()), datetime.combine(
        d2 + timedelta(days=1), time.min, _tz()
    )


def _m(v: Any) -> Decimal:
    return Decimal(v or 0).quantize(CENT)


def _product_filter(category_id: int | None) -> list[Any]:
    conds: list[Any] = [Product.is_active.is_(True)]
    if category_id is not None:
        conds.append(Product.category_id == category_id)
    return conds


def inventory(db: Session, category_id: int | None, with_value: bool) -> dict[str, Any]:
    conds = _product_filter(category_id)
    horizon = today() + timedelta(days=get_settings().expiry_warning_days)

    def count(*extra: Any) -> int:
        return db.scalar(select(func.count(Product.id)).where(*conds, *extra)) or 0

    expiring = db.execute(
        select(
            Product.id,
            Product.name,
            func.min(ProductBatch.expiry_date),
            func.sum(ProductBatch.quantity_remaining),
            Product.unit_of_measure,
        )
        .join(ProductBatch, ProductBatch.product_id == Product.id)
        .where(*conds, ProductBatch.quantity_remaining > 0, ProductBatch.expiry_date <= horizon)
        .group_by(Product.id, Product.name, Product.unit_of_measure)
        .order_by(func.min(ProductBatch.expiry_date))
    ).all()
    low = db.scalars(
        select(Product)
        .where(
            *conds, Product.min_stock_level > 0, Product.quantity_on_hand <= Product.min_stock_level
        )
        .order_by(Product.quantity_on_hand / func.nullif(Product.min_stock_level, 0), Product.name)
    ).all()
    out: dict[str, Any] = {
        "total_products": count(),
        "out_of_stock": count(Product.quantity_on_hand <= 0),
        "low_stock": len(low),
        "low_stock_items": [
            {
                "product_id": p.id,
                "name": p.name,
                "on_hand": p.quantity_on_hand,
                "min_stock": p.min_stock_level,
                "unit": p.unit_of_measure,
            }
            for p in low[:6]
        ],
        "expiring_soon": len(expiring),
        "expiring_items": [
            {
                "product_id": r[0],
                "name": r[1],
                "expiry_date": r[2],
                "quantity": r[3],
                "unit": r[4],
                "expired": r[2] < today(),
            }
            for r in expiring[:6]
        ],
        "inventory_value": None,
    }
    if with_value:
        out["inventory_value"] = _m(
            db.scalar(
                select(
                    func.coalesce(
                        func.sum(func.greatest(Product.quantity_on_hand, 0) * Product.avg_cost), 0
                    )
                ).where(*conds)
            )
        )
    return out


def _sales_lines(
    db: Session, d1: date, d2: date, category_id: int | None
) -> tuple[Decimal, Decimal, int]:
    """Revenue excl. VAT and gross profit, net of refunds, and the number of sales, for the
    period (only the chosen category's lines, if one is chosen)."""
    if category_id is None:
        f = finance_service.summary(db, d1, d2)
        return f["revenue"], f["gross_profit"], f["transactions"]
    cat = set(db.scalars(select(Product.id).where(Product.category_id == category_id)))
    rows = [r for r in finance_service.by_product(db, d1, d2) if r["product_id"] in cat]
    s, e = _bounds(d1, d2)
    n = (
        db.scalar(
            select(func.count(func.distinct(Sale.id)))
            .join(SaleItem, SaleItem.sale_id == Sale.id)
            .join(Product, Product.id == SaleItem.product_id)
            .where(Sale.sold_at >= s, Sale.sold_at < e, Product.category_id == category_id)
        )
        or 0
    )
    return (
        _m(sum((r["revenue"] for r in rows), Decimal(0))),
        _m(sum((r["gross_profit"] for r in rows), Decimal(0))),
        n,
    )


def sales(db: Session, d1: date, d2: date, category_id: int | None) -> dict[str, Any]:
    now = today()
    rev, gp, n = _sales_lines(db, d1, d2, category_id)
    t_rev, _, t_n = _sales_lines(db, now, now, category_id)
    m_rev, m_gp, _ = _sales_lines(db, now.replace(day=1), now, category_id)
    # Daily trend (sales lines; refunds are shown in the period totals above).
    s, e = _bounds(d1, d2)
    day = cast(func.timezone(get_settings().store_timezone, Sale.sold_at), Date)
    q = (
        select(
            day,
            func.sum(SaleItem.line_total - SaleItem.tax_amount),
            func.sum(
                SaleItem.line_total - SaleItem.tax_amount - SaleItem.quantity * SaleItem.unit_cost
            ),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(Sale.sold_at >= s, Sale.sold_at < e)
        .group_by(day)
    )
    if category_id is not None:
        q = q.join(Product, Product.id == SaleItem.product_id).where(
            Product.category_id == category_id
        )
    by_day = {r[0]: (r[1], r[2]) for r in db.execute(q).all()}
    trend = []
    d = d1
    while d <= d2:
        r, p = by_day.get(d, (0, 0))
        trend.append({"day": d, "revenue": _m(r), "gross_profit": _m(p)})
        d += timedelta(days=1)
    return {
        "today_revenue": t_rev,
        "today_transactions": t_n,
        "month_revenue": m_rev,
        "month_gross_profit": m_gp,
        "period_revenue": rev,
        "period_gross_profit": gp,
        "period_transactions": n,
        "gross_margin_percent": _m(gp / rev * 100) if rev > 0 else None,
        "trend": trend,
    }


def movers(
    db: Session, d1: date, d2: date, category_id: int | None
) -> dict[str, list[dict[str, Any]]]:
    """Fast and slow movers by units sold per day over the period."""
    days = (d2 - d1).days + 1
    s, e = _bounds(d1, d2)
    sold = dict(
        db.execute(
            select(SaleItem.product_id, func.sum(SaleItem.quantity))
            .join(Sale, Sale.id == SaleItem.sale_id)
            .where(Sale.sold_at >= s, Sale.sold_at < e)
            .group_by(SaleItem.product_id)
        ).all()
    )
    products = db.scalars(select(Product).where(*_product_filter(category_id))).all()
    rows = [
        {
            "product_id": p.id,
            "name": p.name,
            "unit": p.unit_of_measure,
            "per_day": round(float(sold.get(p.id, 0)) / days, 2),
            "on_hand": p.quantity_on_hand,
            "days_of_cover": round(float(p.quantity_on_hand) / (float(sold[p.id]) / days), 1)
            if sold.get(p.id)
            else None,
        }
        for p in products
    ]
    rows.sort(key=lambda r: r["per_day"], reverse=True)
    n = min(5, max(len(rows) // 2, 1))
    return {"fast": rows[:n], "slow": sorted(rows[n:], key=lambda r: r["per_day"])[:n]}


def shortages(db: Session, category_id: int | None) -> list[dict[str, Any]]:
    run = forecast_service.latest_run(db)
    if run is None:
        return []
    q = (
        select(ProductForecast)
        .join(Product, Product.id == ProductForecast.product_id)
        .where(
            ProductForecast.run_id == run.id,
            ProductForecast.stockout_date.is_not(None),
            *_product_filter(category_id),
        )
        .order_by(ProductForecast.stockout_date)
    )
    out = []
    for pf in db.scalars(q).unique():
        if (pf.stockout_date - today()).days > pf.lead_time_days:
            continue
        out.append(
            {
                "product_id": pf.product_id,
                "name": pf.product.name,
                "stockout_date": pf.stockout_date,
                "lead_time_days": pf.lead_time_days,
                "suggested_quantity": pf.suggested_quantity,
                "unit": pf.product.unit_of_measure,
            }
        )
    return out[:6]


def approvals(db: Session) -> dict[str, int]:
    def n(stmt: Any) -> int:
        return db.scalar(stmt) or 0

    return {
        "invoices_to_review": n(
            select(func.count(Invoice.id)).where(Invoice.status.in_(["NEEDS_REVIEW", "FAILED"]))
        ),
        "purchase_orders_draft": n(
            select(func.count(PurchaseOrder.id)).where(PurchaseOrder.status == "DRAFT")
        ),
        "purchase_orders_open": n(
            select(func.count(PurchaseOrder.id)).where(
                PurchaseOrder.status.in_(["SENT", "PARTIAL"])
            )
        ),
        "adjustments_pending": n(
            select(func.count(StockAdjustment.id)).where(StockAdjustment.status == "PENDING")
        ),
        "returns_pending": n(
            select(func.count(SaleReturn.id)).where(SaleReturn.status == "PENDING")
        ),
    }


def categories_breakdown(db: Session, d1: date, d2: date) -> list[dict[str, Any]]:
    return [
        {"category": r["category"], "revenue": r["revenue"], "gross_profit": r["gross_profit"]}
        for r in finance_service.by_category(db, d1, d2)
    ]


def build(
    db: Session,
    *,
    d1: date,
    d2: date,
    category_id: int | None,
    finance: bool,
    anomalies: bool,
) -> dict[str, Any]:
    if d2 < d1:
        raise ValidationFailed("The end date is before the start date")
    if (d2 - d1).days > 366:
        raise ValidationFailed("Choose a period of at most a year")
    if category_id is not None and db.get(Category, category_id) is None:
        raise ValidationFailed("Category not found")
    out: dict[str, Any] = {
        "date_from": d1,
        "date_to": d2,
        "category_id": category_id,
        "inventory": inventory(db, category_id, with_value=finance),
        "movers": movers(db, d1, d2, category_id),
        "shortages": shortages(db, category_id),
        "approvals": approvals(db),
        "sales": sales(db, d1, d2, category_id) if finance else None,
        "categories": categories_breakdown(db, d1, d2) if finance and category_id is None else None,
        "open_irregularities": None,
    }
    if anomalies:
        out["open_irregularities"] = (
            db.scalar(
                select(func.count(AnomalyAlert.id)).where(
                    and_(
                        AnomalyAlert.status.in_(["OPEN", "INVESTIGATING"]),
                        AnomalyAlert.severity.in_(["MEDIUM", "HIGH"]),
                    )
                )
            )
            or 0
        )
    return out

"""Expenses and financial analytics (all amounts KES).

Definitions used throughout (documented for the project report):

* Sales gross        = what customers paid, VAT included (sum of receipt totals).
* Revenue            = sales excluding VAT, minus refunds excluding VAT.
* Cost of goods sold = units sold x weighted average cost at the moment of sale (frozen on
                       each sale line), minus the cost of resaleable items returned.
* Gross profit       = Revenue - Cost of goods sold.
* Gross margin %     = Gross profit / Revenue x 100.
* Stock losses       = damaged/expired write-offs + damaged customer returns, at cost.
* Net adjustments    = manual stock adjustments at cost (negative means unexplained loss).
* Net profit (est.)  = Gross profit - stock losses + net adjustments - operating expenses.

Sales and refunds are dated by when they happened (sold_at / decided_at) in store time.
"""

from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationFailed
from app.models import (
    Category,
    Expense,
    ExpenseCategory,
    Product,
    Purchase,
    Sale,
    SaleItem,
    SaleReturn,
    SaleReturnItem,
    StockMovement,
    User,
)
from app.schemas.common import PageParams
from app.schemas.finance import ExpenseIn
from app.services import audit_service
from app.services.audit_service import RequestContext

ZERO = Decimal("0")
CENT = Decimal("0.01")


def _m(value: Any) -> Decimal:
    return Decimal(value or 0).quantize(CENT, ROUND_HALF_UP)


def _bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    if date_to < date_from:
        raise ValidationFailed("The end date is before the start date")
    if (date_to - date_from).days > 731:
        raise ValidationFailed("Choose a period of at most two years")
    tz = ZoneInfo(get_settings().store_timezone)
    return (
        datetime.combine(date_from, time.min, tz),
        datetime.combine(date_to + timedelta(days=1), time.min, tz),
    )


def _local_day(column):  # type: ignore[no-untyped-def]
    return cast(func.timezone(get_settings().store_timezone, column), Date)


# --- Expenses ------------------------------------------------------------------------


def categories(db: Session) -> list[ExpenseCategory]:
    return list(db.scalars(select(ExpenseCategory).order_by(ExpenseCategory.name)))


def _snapshot(e: Expense) -> dict[str, Any]:
    return {
        "category_id": e.category_id,
        "expense_date": e.expense_date,
        "amount": e.amount,
        "description": e.description,
        "payment_method": e.payment_method,
        "reference": e.reference,
    }


def _check_category(db: Session, category_id: int) -> None:
    cat = db.get(ExpenseCategory, category_id)
    if cat is None or not cat.is_active:
        raise ValidationFailed(
            "Choose an expense category", details=[{"field": "category_id", "message": "not found"}]
        )


def create_expense(db: Session, data: ExpenseIn, user: User, ctx: RequestContext) -> Expense:
    _check_category(db, data.category_id)
    if data.expense_date > date.today() + timedelta(days=1):
        raise ValidationFailed("The expense date is in the future")
    exp = Expense(**data.model_dump(), recorded_by_id=user.id)
    exp.description = exp.description.strip()
    db.add(exp)
    db.flush()
    audit_service.record(
        db,
        action="expense.create",
        actor=user,
        ctx=ctx,
        entity_type="expense",
        entity_id=exp.id,
        after=_snapshot(exp),
    )
    db.commit()
    db.refresh(exp)
    return exp


def get_expense(db: Session, expense_id: int) -> Expense:
    exp = db.get(Expense, expense_id)
    if exp is None:
        raise NotFoundError("Expense not found")
    return exp


def update_expense(
    db: Session, exp: Expense, data: ExpenseIn, user: User, ctx: RequestContext
) -> Expense:
    _check_category(db, data.category_id)
    before = _snapshot(exp)
    for key, value in data.model_dump().items():
        setattr(exp, key, value)
    db.flush()
    old, new = audit_service.diff(before, _snapshot(exp))
    if new:
        audit_service.record(
            db,
            action="expense.update",
            actor=user,
            ctx=ctx,
            entity_type="expense",
            entity_id=exp.id,
            before=old,
            after=new,
        )
    db.commit()
    db.refresh(exp)
    return exp


def delete_expense(db: Session, exp: Expense, user: User, ctx: RequestContext) -> None:
    audit_service.record(
        db,
        action="expense.delete",
        actor=user,
        ctx=ctx,
        entity_type="expense",
        entity_id=exp.id,
        before=_snapshot(exp),
    )
    db.delete(exp)
    db.commit()


def list_expenses(
    db: Session,
    params: PageParams,
    *,
    date_from: date | None,
    date_to: date | None,
    category_id: int | None,
) -> tuple[list[Expense], int, Decimal]:
    stmt = select(Expense)
    if date_from:
        stmt = stmt.where(Expense.expense_date >= date_from)
    if date_to:
        stmt = stmt.where(Expense.expense_date <= date_to)
    if category_id:
        stmt = stmt.where(Expense.category_id == category_id)
    sub = stmt.subquery()
    total = db.scalar(select(func.count()).select_from(sub)) or 0
    amount = _m(db.scalar(select(func.coalesce(func.sum(sub.c.amount), 0))))
    rows = db.scalars(
        stmt.order_by(Expense.expense_date.desc(), Expense.id.desc())
        .offset(params.offset)
        .limit(params.page_size)
    ).all()
    return list(rows), total, amount


# --- Analytics -------------------------------------------------------------------------


def _vat_part(amount_col, rate_col):  # type: ignore[no-untyped-def]
    """VAT contained in a VAT-inclusive amount, in SQL."""
    return amount_col * rate_col / (100 + rate_col)


def summary(db: Session, date_from: date, date_to: date) -> dict[str, Any]:
    start, end = _bounds(date_from, date_to)
    in_range = (Sale.sold_at >= start, Sale.sold_at < end)

    sales = db.execute(
        select(
            func.count(Sale.id),
            func.coalesce(func.sum(Sale.grand_total), 0),
            func.coalesce(func.sum(Sale.tax_total), 0),
            func.coalesce(func.sum(Sale.discount_total), 0),
        ).where(*in_range)
    ).one()
    lines = db.execute(
        select(
            func.coalesce(func.sum(SaleItem.quantity), 0),
            func.coalesce(func.sum(SaleItem.quantity * SaleItem.unit_cost), 0),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(*in_range)
    ).one()

    returned = (
        select(
            func.coalesce(func.sum(SaleReturnItem.refund_amount), 0),
            func.coalesce(func.sum(_vat_part(SaleReturnItem.refund_amount, SaleItem.vat_rate)), 0),
            func.coalesce(
                func.sum(
                    case(
                        (
                            SaleReturnItem.condition == "RESALEABLE",
                            SaleReturnItem.quantity * SaleItem.unit_cost,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            SaleReturnItem.condition == "DAMAGED",
                            SaleReturnItem.quantity * SaleItem.unit_cost,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .join(SaleReturn, SaleReturn.id == SaleReturnItem.return_id)
        .join(SaleItem, SaleItem.id == SaleReturnItem.sale_item_id)
        .where(
            SaleReturn.status == "APPROVED",
            SaleReturn.decided_at >= start,
            SaleReturn.decided_at < end,
        )
    )
    refunds_gross, refunds_vat, returned_cost, damaged_return_cost = db.execute(returned).one()

    def movement_value(*types: str) -> Decimal:
        return Decimal(
            db.scalar(
                select(
                    func.coalesce(func.sum(StockMovement.quantity * StockMovement.unit_cost), 0)
                ).where(
                    StockMovement.movement_type.in_(types),
                    StockMovement.created_at >= start,
                    StockMovement.created_at < end,
                )
            )
            or 0
        )

    write_offs = -movement_value("DAMAGED", "EXPIRED")  # positive loss
    adjustments = movement_value("ADJUSTMENT_IN", "ADJUSTMENT_OUT")  # signed
    expenses = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(Expense.amount), 0)).where(
                Expense.expense_date >= date_from, Expense.expense_date <= date_to
            )
        )
        or 0
    )
    purchases = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(Purchase.grand_total), 0)).where(
                Purchase.received_at >= start, Purchase.received_at < end
            )
        )
        or 0
    )

    count, gross, vat, discounts = sales
    revenue = (Decimal(gross) - Decimal(vat)) - (Decimal(refunds_gross) - Decimal(refunds_vat))
    cogs = Decimal(lines[1]) - Decimal(returned_cost)
    gross_profit = revenue - cogs
    losses = write_offs + Decimal(damaged_return_cost)
    net = gross_profit - losses + adjustments - expenses
    return {
        "date_from": date_from,
        "date_to": date_to,
        "transactions": count,
        "items_sold": Decimal(lines[0]),
        "sales_gross": _m(gross),
        "vat_collected": _m(vat),
        "refunds_gross": _m(refunds_gross),
        "revenue": _m(revenue),
        "cost_of_goods_sold": _m(cogs),
        "gross_profit": _m(gross_profit),
        "gross_margin_percent": _m(gross_profit / revenue * 100) if revenue > 0 else None,
        "stock_losses": _m(losses),
        "net_adjustments": _m(adjustments),
        "operating_expenses": _m(expenses),
        "net_profit_estimate": _m(net),
        "purchases_total": _m(purchases),
        "average_basket": _m(Decimal(gross) / count) if count else None,
        "discounts_given": _m(discounts),
    }


def daily(db: Session, date_from: date, date_to: date) -> list[dict[str, Any]]:
    start, end = _bounds(date_from, date_to)
    day = _local_day(Sale.sold_at)
    sales = {
        r[0]: r
        for r in db.execute(
            select(
                day,
                func.count(func.distinct(Sale.id)),
                func.coalesce(func.sum(SaleItem.line_total - SaleItem.tax_amount), 0),
                func.coalesce(func.sum(SaleItem.quantity * SaleItem.unit_cost), 0),
            )
            .join(SaleItem, SaleItem.sale_id == Sale.id)
            .where(Sale.sold_at >= start, Sale.sold_at < end)
            .group_by(day)
        ).all()
    }
    rday = _local_day(SaleReturn.decided_at)
    returns = {
        r[0]: r
        for r in db.execute(
            select(
                rday,
                func.coalesce(
                    func.sum(
                        SaleReturnItem.refund_amount
                        - _vat_part(SaleReturnItem.refund_amount, SaleItem.vat_rate)
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                SaleReturnItem.condition == "RESALEABLE",
                                SaleReturnItem.quantity * SaleItem.unit_cost,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
            .join(SaleReturn, SaleReturn.id == SaleReturnItem.return_id)
            .join(SaleItem, SaleItem.id == SaleReturnItem.sale_item_id)
            .where(
                SaleReturn.status == "APPROVED",
                SaleReturn.decided_at >= start,
                SaleReturn.decided_at < end,
            )
            .group_by(rday)
        ).all()
    }
    points = []
    d = date_from
    while d <= date_to:
        s = sales.get(d)
        r = returns.get(d)
        revenue = (Decimal(s[2]) if s else ZERO) - (Decimal(r[1]) if r else ZERO)
        cogs = (Decimal(s[3]) if s else ZERO) - (Decimal(r[2]) if r else ZERO)
        points.append(
            {
                "day": d,
                "revenue": _m(revenue),
                "cost_of_goods_sold": _m(cogs),
                "gross_profit": _m(revenue - cogs),
                "transactions": s[1] if s else 0,
            }
        )
        d += timedelta(days=1)
    return points


def by_product(db: Session, date_from: date, date_to: date) -> list[dict[str, Any]]:
    start, end = _bounds(date_from, date_to)
    sold = db.execute(
        select(
            SaleItem.product_id,
            func.sum(SaleItem.quantity),
            func.sum(SaleItem.line_total - SaleItem.tax_amount),
            func.sum(SaleItem.quantity * SaleItem.unit_cost),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(Sale.sold_at >= start, Sale.sold_at < end)
        .group_by(SaleItem.product_id)
    ).all()
    back = {
        r[0]: r
        for r in db.execute(
            select(
                SaleItem.product_id,
                func.sum(SaleReturnItem.quantity),
                func.sum(
                    SaleReturnItem.refund_amount
                    - _vat_part(SaleReturnItem.refund_amount, SaleItem.vat_rate)
                ),
                func.sum(
                    case(
                        (
                            SaleReturnItem.condition == "RESALEABLE",
                            SaleReturnItem.quantity * SaleItem.unit_cost,
                        ),
                        else_=0,
                    )
                ),
            )
            .join(SaleReturn, SaleReturn.id == SaleReturnItem.return_id)
            .join(SaleItem, SaleItem.id == SaleReturnItem.sale_item_id)
            .where(
                SaleReturn.status == "APPROVED",
                SaleReturn.decided_at >= start,
                SaleReturn.decided_at < end,
            )
            .group_by(SaleItem.product_id)
        ).all()
    }
    ids = {r[0] for r in sold} | set(back)
    info = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(ids)))} if ids else {}
    cat_names = dict(db.execute(select(Category.id, Category.name)).all())
    sold_by = {r[0]: r for r in sold}
    rows = []
    for pid in ids:
        s, r = sold_by.get(pid), back.get(pid)
        qty = (Decimal(s[1]) if s else ZERO) - (Decimal(r[1]) if r else ZERO)
        revenue = (Decimal(s[2]) if s else ZERO) - (Decimal(r[2] or 0) if r else ZERO)
        cogs = (Decimal(s[3]) if s else ZERO) - (Decimal(r[3] or 0) if r else ZERO)
        p = info[pid]
        rows.append(
            {
                "product_id": pid,
                "name": p.name,
                "sku": p.sku,
                "category": cat_names.get(p.category_id),
                "quantity": qty,
                "revenue": _m(revenue),
                "cost_of_goods_sold": _m(cogs),
                "gross_profit": _m(revenue - cogs),
                "margin_percent": _m((revenue - cogs) / revenue * 100) if revenue > 0 else None,
            }
        )
    rows.sort(key=lambda row: row["gross_profit"], reverse=True)
    return rows


def by_category(db: Session, date_from: date, date_to: date) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Decimal]] = {}
    for row in by_product(db, date_from, date_to):
        g = groups.setdefault(
            row["category"] or "Uncategorised",
            {"quantity": ZERO, "revenue": ZERO, "cost_of_goods_sold": ZERO},
        )
        g["quantity"] += row["quantity"]
        g["revenue"] += row["revenue"]
        g["cost_of_goods_sold"] += row["cost_of_goods_sold"]
    out = []
    for name, g in groups.items():
        profit = g["revenue"] - g["cost_of_goods_sold"]
        out.append(
            {
                "category": name,
                **g,
                "gross_profit": _m(profit),
                "margin_percent": _m(profit / g["revenue"] * 100) if g["revenue"] > 0 else None,
            }
        )
    out.sort(key=lambda row: row["revenue"], reverse=True)
    return out


def payment_breakdown(db: Session, date_from: date, date_to: date) -> list[dict[str, Any]]:
    start, end = _bounds(date_from, date_to)
    rows = db.execute(
        select(Sale.payment_method, func.count(Sale.id), func.sum(Sale.grand_total))
        .where(Sale.sold_at >= start, Sale.sold_at < end)
        .group_by(Sale.payment_method)
        .order_by(func.sum(Sale.grand_total).desc())
    ).all()
    return [{"payment_method": r[0], "transactions": r[1], "total": _m(r[2])} for r in rows]

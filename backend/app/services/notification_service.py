"""In-app notifications: who gets them, de-duplication, and the periodic checks.

A notification goes to every active user whose role has one of the given permissions
(for example low stock goes to whoever can order stock). Each person gets their own copy
so read/unread is personal. `dedupe_key` (unique per user) stops repeats: the low-stock
alert for a product is sent at most once a day.
"""

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.permissions import P
from app.models import Notification, Product, ProductBatch, User
from app.models.invoice import Invoice
from app.models.sales import SaleReturn
from app.models.stock import StockAdjustment


def _today() -> date:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(get_settings().store_timezone)).date()


def recipients(db: Session, perms: Iterable[P]) -> list[User]:
    codes = {p.value for p in perms}
    users = db.scalars(select(User).where(User.is_active)).unique().all()
    return [u for u in users if codes & u.permission_codes]


def notify(
    db: Session,
    *,
    perms: Iterable[P],
    type: str,
    title: str,
    message: str,
    dedupe_key: str,
    link: str | None = None,
    severity: str = "info",
) -> int:
    """Create the notification for everyone concerned; returns how many were new.
    Does not commit: it joins the caller's transaction."""
    users = recipients(db, perms)
    if not users:
        return 0
    rows = [
        {
            "user_id": u.id,
            "type": type,
            "title": title[:200],
            "message": message,
            "link": link,
            "severity": severity,
            "dedupe_key": dedupe_key[:150],
        }
        for u in users
    ]
    inserted = db.execute(
        insert(Notification)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_notification_dedupe")
        .returning(Notification.id)
    ).all()
    return len(inserted)


# --- Real-time: called from the stock ledger ----------------------------------------------


def stock_level_changed(db: Session, product: Product, before: Decimal, after: Decimal) -> None:
    """Low / out of stock, at the moment a movement crosses the line (not on every sale)."""
    if after >= before:
        return
    today = _today()
    if after <= 0 < before:
        notify(
            db,
            perms=[P.PURCHASES_WRITE],
            type="OUT_OF_STOCK",
            severity="critical",
            title=f"Out of stock: {product.name}",
            message=f"{product.name} has run out. Reorder it or check for stock in the store room.",
            link=f"/products/{product.id}",
            dedupe_key=f"out-of-stock:{product.id}:{today}",
        )
    elif after <= product.min_stock_level < before:
        notify(
            db,
            perms=[P.PURCHASES_WRITE],
            type="LOW_STOCK",
            severity="warning",
            title=f"Low stock: {product.name}",
            message=f"{product.name} is down to {after.normalize():f} "
            f"{product.unit_of_measure} (minimum {product.min_stock_level.normalize():f}).",
            link=f"/products/{product.id}",
            dedupe_key=f"low-stock:{product.id}:{today}",
        )


# --- Periodic sweep ---------------------------------------------------------------------


def sweep(db: Session) -> dict[str, int]:
    """Expiring batches and approvals that are waiting. Run every few minutes by the worker."""
    settings = get_settings()
    today = _today()
    counts = {"expiry": 0, "approvals": 0}

    soon = today + timedelta(days=settings.expiry_warning_days)
    batches = db.scalars(
        select(ProductBatch).where(
            ProductBatch.quantity_remaining > 0,
            ProductBatch.expiry_date.is_not(None),
            ProductBatch.expiry_date <= soon,
        )
    ).all()
    for b in batches:
        p = db.get(Product, b.product_id)
        if p is None or not p.is_active:
            continue
        days = (b.expiry_date - today).days
        when = (
            "has expired"
            if days < 0
            else "expires today"
            if days == 0
            else f"expires in {days} days"
        )
        counts["expiry"] += notify(
            db,
            perms=[P.STOCK_WRITE_OFF, P.PURCHASES_WRITE],
            type="EXPIRY",
            severity="critical" if days <= 2 else "warning",
            title=f"{p.name}: batch {when}",
            message=f"{b.quantity_remaining.normalize():f} {p.unit_of_measure} of {p.name}"
            f"{f' (batch {b.batch_number})' if b.batch_number else ''} {when} "
            f"({b.expiry_date:%d %b}). Sell it first, discount it, or write it off.",
            link=f"/products/{p.id}",
            dedupe_key=f"expiry:{b.id}:{today}",
        )

    cutoff = datetime.now(UTC) - timedelta(hours=24)
    waiting = (
        db.scalar(
            select(func.count())
            .select_from(Invoice)
            .where(Invoice.status == "NEEDS_REVIEW", Invoice.created_at < cutoff)
        )
        or 0
    )
    if waiting:
        counts["approvals"] += notify(
            db,
            perms=[P.INVOICES_APPROVE],
            type="PENDING_APPROVAL",
            severity="warning",
            title=f"{waiting} scanned invoice{'s' if waiting > 1 else ''} waiting over 24 hours",
            message="Supplier invoices are waiting for review; stock is not updated until they "
            "are approved.",
            link="/purchasing/invoices",
            dedupe_key=f"invoices-waiting:{today}",
        )
    adjustments = (
        db.scalar(
            select(func.count())
            .select_from(StockAdjustment)
            .where(StockAdjustment.status == "PENDING")
        )
        or 0
    )
    if adjustments:
        counts["approvals"] += notify(
            db,
            perms=[P.STOCK_ADJUST_APPROVE],
            type="PENDING_APPROVAL",
            severity="warning",
            title=f"{adjustments} stock adjustment{'s' if adjustments > 1 else ''} to approve",
            message="Large stock adjustments are waiting for a manager's decision.",
            link="/stock/adjustments",
            dedupe_key=f"adjustments-waiting:{today}:{adjustments}",
        )
    returns = (
        db.scalar(
            select(func.count()).select_from(SaleReturn).where(SaleReturn.status == "PENDING")
        )
        or 0
    )
    if returns:
        counts["approvals"] += notify(
            db,
            perms=[P.RETURNS_APPROVE],
            type="PENDING_APPROVAL",
            severity="warning",
            title=f"{returns} customer return{'s' if returns > 1 else ''} to approve",
            message="Refunds requested at the till are waiting for approval.",
            link="/returns",
            dedupe_key=f"returns-waiting:{today}:{returns}",
        )
    return counts


# --- Reading ----------------------------------------------------------------------------


def list_for(
    db: Session, user: User, *, unread_only: bool, limit: int, offset: int
) -> tuple[list[Notification], int, int]:
    base = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        base = base.where(Notification.is_read.is_(False))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return list(rows), total, unread_count(db, user)


def unread_count(db: Session, user: User) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        )
        or 0
    )


def mark_read(db: Session, user: User, ids: list[int] | None) -> int:
    stmt = update(Notification).where(
        Notification.user_id == user.id, Notification.is_read.is_(False)
    )
    if ids is not None:
        stmt = stmt.where(Notification.id.in_(ids))
    n = db.execute(stmt.values(is_read=True, read_at=datetime.now(UTC))).rowcount or 0
    db.commit()
    return n

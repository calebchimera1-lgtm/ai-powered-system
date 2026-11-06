"""Manual stock adjustments (with approval), write-offs and stock reporting queries."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, PermissionDenied, ValidationFailed
from app.core.permissions import P
from app.models import Product, ProductBatch, StockAdjustment, StockMovement, User
from app.schemas.common import PageParams
from app.schemas.stock import AdjustmentCreate, WriteOffCreate
from app.services import audit_service, inventory_service
from app.services.audit_service import RequestContext
from app.services.inventory_service import fmt, q

REASON_LABELS = {
    "COUNT_CORRECTION": "Stock count correction",
    "FOUND_STOCK": "Found stock",
    "DATA_ENTRY_ERROR": "Data entry error",
    "THEFT_SUSPECTED": "Suspected loss",
    "INTERNAL_USE": "Internal use",
    "OTHER": "Other",
}


def _now() -> datetime:
    return datetime.now(UTC)


# --- Adjustments -------------------------------------------------------------------


def _check_negative(product: Product, change: Decimal, allow_negative: bool, user: User) -> None:
    result = product.quantity_on_hand + change
    if result >= 0:
        return
    if not allow_negative:
        raise ValidationFailed(
            f"This would leave {fmt(result)} {product.unit_of_measure} of {product.name}, "
            "below zero. Only a Super Administrator can authorise negative stock.",
            code="NEGATIVE_STOCK",
        )
    if P.STOCK_ADJUST_NEGATIVE.value not in user.permission_codes:
        raise PermissionDenied("Only a Super Administrator can authorise negative stock.")


def _apply(db: Session, adj: StockAdjustment, product: Product, user: User) -> None:
    reason = REASON_LABELS[adj.reason_code] + (f": {adj.notes}" if adj.notes else "")
    inventory_service.apply_movement(
        db,
        product_id=product.id,
        quantity=adj.quantity_change,
        movement_type="ADJUSTMENT_IN" if adj.quantity_change > 0 else "ADJUSTMENT_OUT",
        user=user,
        batch_id=adj.batch_id,
        batch_info=inventory_service.BatchInfo(expiry_date=adj.expiry_date)
        if adj.quantity_change > 0
        else None,
        reference_type="stock_adjustment",
        reference_id=adj.id,
        reason=reason,
        allow_negative=adj.allow_negative,
    )


def create_adjustment(
    db: Session, data: AdjustmentCreate, user: User, ctx: RequestContext
) -> tuple[StockAdjustment, bool]:
    """Record an adjustment. Small ones (or by an approver) apply immediately; others wait.

    Returns (adjustment, applied).
    """
    settings = get_settings()
    product = inventory_service.lock_product(db, data.product_id)
    if not product.is_active:
        raise ValidationFailed("This product is deactivated")

    system_qty = product.quantity_on_hand
    if data.counted_quantity is not None:
        change = q(data.counted_quantity) - system_qty
        if change == 0:
            raise ValidationFailed(
                f"The count matches the system ({fmt(system_qty)} {product.unit_of_measure}); "
                "nothing to adjust."
            )
    else:
        change = q(data.quantity_change)  # type: ignore[arg-type]
    inventory_service.validate_quantity(product, change)
    _check_negative(product, change, data.allow_negative, user)

    if data.batch_id is not None:
        batch = db.get(ProductBatch, data.batch_id)
        if batch is None or batch.product_id != product.id:
            raise ValidationFailed("That batch does not belong to this product")
    if change > 0 and product.tracks_expiry and not (data.batch_id or data.expiry_date):
        raise ValidationFailed(
            f"{product.name} tracks expiry dates: choose the batch or enter an expiry date",
            details=[{"field": "expiry_date", "message": "required for this product"}],
        )

    value = (abs(change) * product.avg_cost).quantize(Decimal("0.01"), ROUND_HALF_UP)
    can_approve = P.STOCK_ADJUST_APPROVE.value in user.permission_codes
    needs_approval = value > settings.stock_adjustment_approval_threshold and not can_approve

    adj = StockAdjustment(
        product_id=product.id,
        batch_id=data.batch_id,
        reason_code=data.reason_code,
        notes=(data.notes or "").strip() or None,
        system_quantity=system_qty,
        counted_quantity=q(data.counted_quantity) if data.counted_quantity is not None else None,
        quantity_change=change,
        expiry_date=data.expiry_date,
        unit_cost=product.avg_cost,
        value_impact=value,
        allow_negative=data.allow_negative,
        status="PENDING",
        requested_by_id=user.id,
    )
    db.add(adj)
    db.flush()

    if not needs_approval:
        adj.status = "APPROVED"
        adj.decided_by_id = user.id
        adj.decided_at = _now()
        adj.decision_note = "Applied immediately"
        _apply(db, adj, product, user)

    audit_service.record(
        db,
        action="stock.adjustment_applied" if not needs_approval else "stock.adjustment_requested",
        actor=user,
        ctx=ctx,
        entity_type="stock_adjustment",
        entity_id=adj.id,
        after={
            "product": product.name,
            "system_quantity": system_qty,
            "change": change,
            "value_kes": value,
            "reason": adj.reason_code,
        },
    )
    db.commit()
    db.refresh(adj)
    return adj, not needs_approval


def get_adjustment(db: Session, adj_id: int) -> StockAdjustment:
    adj = db.get(StockAdjustment, adj_id)
    if adj is None:
        raise NotFoundError("Adjustment not found")
    return adj


def approve_adjustment(
    db: Session,
    adj: StockAdjustment,
    user: User,
    ctx: RequestContext,
    *,
    note: str | None,
    allow_negative: bool,
) -> StockAdjustment:
    if adj.status != "PENDING":
        raise ValidationFailed(f"This adjustment is already {adj.status.lower()}")
    if adj.requested_by_id == user.id:
        raise PermissionDenied("Someone else must approve your own adjustment request.")
    product = inventory_service.lock_product(db, adj.product_id)
    adj.allow_negative = adj.allow_negative or allow_negative
    # Stock may have moved since the request; re-check against the current balance.
    _check_negative(product, adj.quantity_change, adj.allow_negative, user)
    adj.status = "APPROVED"
    adj.decided_by_id = user.id
    adj.decided_at = _now()
    adj.decision_note = (note or "").strip() or None
    _apply(db, adj, product, user)
    audit_service.record(
        db,
        action="stock.adjustment_approved",
        actor=user,
        ctx=ctx,
        entity_type="stock_adjustment",
        entity_id=adj.id,
        details=adj.decision_note,
    )
    db.commit()
    db.refresh(adj)
    return adj


def reject_adjustment(
    db: Session, adj: StockAdjustment, user: User, ctx: RequestContext, *, note: str | None
) -> StockAdjustment:
    if adj.status != "PENDING":
        raise ValidationFailed(f"This adjustment is already {adj.status.lower()}")
    if not (note or "").strip():
        raise ValidationFailed(
            "Please give a reason for rejecting",
            details=[{"field": "note", "message": "required"}],
        )
    adj.status = "REJECTED"
    adj.decided_by_id = user.id
    adj.decided_at = _now()
    adj.decision_note = note.strip()  # type: ignore[union-attr]
    audit_service.record(
        db,
        action="stock.adjustment_rejected",
        actor=user,
        ctx=ctx,
        entity_type="stock_adjustment",
        entity_id=adj.id,
        details=adj.decision_note,
    )
    db.commit()
    db.refresh(adj)
    return adj


def list_adjustments(
    db: Session,
    params: PageParams,
    *,
    status: str | None,
    product_id: int | None,
) -> tuple[list[StockAdjustment], int]:
    stmt = select(StockAdjustment)
    if status:
        stmt = stmt.where(StockAdjustment.status == status)
    if product_id:
        stmt = stmt.where(StockAdjustment.product_id == product_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(StockAdjustment.created_at.desc(), StockAdjustment.id.desc())
        .offset(params.offset)
        .limit(params.page_size)
    ).all()
    return list(rows), total


# --- Write-offs --------------------------------------------------------------------


def write_off(
    db: Session, data: WriteOffCreate, user: User, ctx: RequestContext
) -> tuple[list[StockMovement], Product]:
    if data.kind == "EXPIRED" and data.batch_id is not None:
        batch = db.get(ProductBatch, data.batch_id)
        if batch is not None and batch.expiry_date and batch.expiry_date > date.today():
            raise ValidationFailed(
                f"That batch expires on {batch.expiry_date:%d %b %Y}; record it as damaged "
                "if it cannot be sold."
            )
    label = "Damaged goods" if data.kind == "DAMAGED" else "Expired goods"
    movements = inventory_service.apply_movement(
        db,
        product_id=data.product_id,
        quantity=-data.quantity,
        movement_type=data.kind,
        user=user,
        batch_id=data.batch_id,
        reference_type="write_off",
        reason=label + (f": {data.notes.strip()}" if data.notes and data.notes.strip() else ""),
    )
    product = movements[0].product
    value = sum((-m.quantity * m.unit_cost for m in movements), Decimal("0"))
    audit_service.record(
        db,
        action="stock.write_off",
        actor=user,
        ctx=ctx,
        entity_type="product",
        entity_id=product.id,
        after={
            "kind": data.kind,
            "quantity": data.quantity,
            "value_kes": value.quantize(Decimal("0.01")),
        },
        details=data.notes,
    )
    db.commit()
    for m in movements:
        db.refresh(m)
    db.refresh(product)
    return movements, product


# --- Reporting ---------------------------------------------------------------------


def list_movements(
    db: Session,
    params: PageParams,
    *,
    product_id: int | None = None,
    movement_type: str | None = None,
    user_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[StockMovement], int]:
    tz = ZoneInfo(get_settings().store_timezone)
    stmt = select(StockMovement)
    if product_id:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if movement_type:
        types = [t.strip() for t in movement_type.split(",") if t.strip()]
        stmt = stmt.where(StockMovement.movement_type.in_(types))
    if user_id:
        stmt = stmt.where(StockMovement.user_id == user_id)
    if date_from:
        stmt = stmt.where(StockMovement.created_at >= datetime.combine(date_from, time.min, tz))
    if date_to:
        end = datetime.combine(date_to + timedelta(days=1), time.min, tz)
        stmt = stmt.where(StockMovement.created_at < end)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
        .offset(params.offset)
        .limit(params.page_size)
    ).all()
    return list(rows), total


def summary(db: Session) -> dict[str, object]:
    settings = get_settings()
    active = Product.is_active.is_(True)
    today = date.today()
    horizon = today + timedelta(days=settings.expiry_warning_days)

    def count(*conds) -> int:  # type: ignore[no-untyped-def]
        return db.scalar(select(func.count(Product.id)).where(active, *conds)) or 0

    def batch_count(*conds) -> int:  # type: ignore[no-untyped-def]
        return (
            db.scalar(
                select(func.count(func.distinct(ProductBatch.product_id)))
                .join(Product, Product.id == ProductBatch.product_id)
                .where(active, ProductBatch.quantity_remaining > 0, *conds)
            )
            or 0
        )

    value = db.scalar(
        select(
            func.coalesce(
                func.sum(func.greatest(Product.quantity_on_hand, 0) * Product.avg_cost), 0
            )
        ).where(active)
    )
    return {
        "active_products": count(),
        "out_of_stock": count(Product.quantity_on_hand <= 0),
        "low_stock": count(
            Product.quantity_on_hand > 0,
            Product.min_stock_level > 0,
            Product.quantity_on_hand <= Product.min_stock_level,
        ),
        "expiring_soon": batch_count(
            ProductBatch.expiry_date >= today, ProductBatch.expiry_date <= horizon
        ),
        "expired_in_stock": batch_count(ProductBatch.expiry_date < today),
        "pending_adjustments": db.scalar(
            select(func.count(StockAdjustment.id)).where(StockAdjustment.status == "PENDING")
        )
        or 0,
        "inventory_value": Decimal(value).quantize(Decimal("0.01"), ROUND_HALF_UP),
    }

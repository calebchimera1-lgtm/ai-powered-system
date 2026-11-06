"""Stock ledger, adjustments, write-offs and summary."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Ctx, DbSession, Pagination, require
from app.core.permissions import P
from app.models import StockAdjustment, StockMovement, User
from app.schemas.common import Page
from app.schemas.stock import (
    AdjustmentCreate,
    AdjustmentDecision,
    AdjustmentOut,
    AdjustmentResult,
    MovementOut,
    StockSummary,
    WriteOffCreate,
    WriteOffResult,
)
from app.services import stock_service
from app.services.inventory_service import fmt

router = APIRouter(prefix="/stock", tags=["Stock"])

Reader = Annotated[User, Depends(require(P.STOCK_READ))]


def _cost(user: User) -> bool:
    return P.PRODUCTS_VIEW_COST.value in user.permission_codes


def movement_out(m: StockMovement, *, with_cost: bool) -> MovementOut:
    item = MovementOut.model_validate(m)
    item.batch_number = m.batch.batch_number if m.batch else None
    if with_cost:
        item.value = (m.quantity * m.unit_cost).quantize(m.unit_cost.__class__("0.01"))
    else:
        item.unit_cost = None
    return item


def adjustment_out(a: StockAdjustment, *, with_cost: bool) -> AdjustmentOut:
    item = AdjustmentOut.model_validate(a)
    if not with_cost:
        item.value_impact = None
    return item


@router.get("/summary", response_model=StockSummary)
def stock_summary(user: Reader, db: DbSession) -> StockSummary:
    data = stock_service.summary(db)
    if not _cost(user):
        data["inventory_value"] = None
    return StockSummary.model_validate(data)


@router.get("/movements", response_model=Page[MovementOut])
def list_movements(
    user: Reader,
    db: DbSession,
    pagination: Pagination,
    product_id: int | None = None,
    movement_type: Annotated[str | None, Query(max_length=200)] = None,
    user_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Page[MovementOut]:
    """The stock ledger, newest first. `movement_type` accepts a comma-separated list."""
    rows, total = stock_service.list_movements(
        db,
        pagination,
        product_id=product_id,
        movement_type=movement_type,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
    )
    with_cost = _cost(user)
    return Page.build([movement_out(m, with_cost=with_cost) for m in rows], total, pagination)


@router.get("/adjustments", response_model=Page[AdjustmentOut])
def list_adjustments(
    user: Reader,
    db: DbSession,
    pagination: Pagination,
    status_filter: Annotated[
        Literal["PENDING", "APPROVED", "REJECTED"] | None, Query(alias="status")
    ] = None,
    product_id: int | None = None,
) -> Page[AdjustmentOut]:
    rows, total = stock_service.list_adjustments(
        db, pagination, status=status_filter, product_id=product_id
    )
    with_cost = _cost(user)
    return Page.build([adjustment_out(a, with_cost=with_cost) for a in rows], total, pagination)


@router.post("/adjustments", response_model=AdjustmentResult, status_code=status.HTTP_201_CREATED)
def create_adjustment(
    body: AdjustmentCreate,
    user: Annotated[User, Depends(require(P.STOCK_ADJUST))],
    db: DbSession,
    ctx: Ctx,
) -> AdjustmentResult:
    """Record a stock count or correction. Large changes wait for manager approval."""
    adj, applied = stock_service.create_adjustment(db, body, user, ctx)
    unit = adj.product.unit_of_measure
    amount = f"{fmt(abs(adj.quantity_change))} {unit}"
    direction = "increased" if adj.quantity_change > 0 else "reduced"
    message = (
        f"Stock of {adj.product.name} {direction} by {amount}."
        if applied
        else f"Change of {'+' if adj.quantity_change > 0 else '−'}{amount} sent to a manager "
        "for approval."
    )
    return AdjustmentResult(
        adjustment=adjustment_out(adj, with_cost=_cost(user)), applied=applied, message=message
    )


Approver = Annotated[User, Depends(require(P.STOCK_ADJUST_APPROVE))]


@router.post("/adjustments/{adjustment_id}/approve", response_model=AdjustmentOut)
def approve(
    adjustment_id: int, body: AdjustmentDecision, user: Approver, db: DbSession, ctx: Ctx
) -> AdjustmentOut:
    adj = stock_service.get_adjustment(db, adjustment_id)
    adj = stock_service.approve_adjustment(
        db, adj, user, ctx, note=body.note, allow_negative=body.allow_negative
    )
    return adjustment_out(adj, with_cost=_cost(user))


@router.post("/adjustments/{adjustment_id}/reject", response_model=AdjustmentOut)
def reject(
    adjustment_id: int, body: AdjustmentDecision, user: Approver, db: DbSession, ctx: Ctx
) -> AdjustmentOut:
    adj = stock_service.get_adjustment(db, adjustment_id)
    return adjustment_out(
        stock_service.reject_adjustment(db, adj, user, ctx, note=body.note),
        with_cost=_cost(user),
    )


@router.post("/write-offs", response_model=WriteOffResult, status_code=status.HTTP_201_CREATED)
def write_off(
    body: WriteOffCreate,
    user: Annotated[User, Depends(require(P.STOCK_WRITE_OFF))],
    db: DbSession,
    ctx: Ctx,
) -> WriteOffResult:
    """Remove damaged or expired goods from stock (FEFO unless a batch is chosen)."""
    movements, product = stock_service.write_off(db, body, user, ctx)
    with_cost = _cost(user)
    value = sum((-m.quantity * m.unit_cost for m in movements), product.avg_cost * 0)
    return WriteOffResult(
        movements=[movement_out(m, with_cost=with_cost) for m in movements],
        quantity_on_hand=product.quantity_on_hand,
        value_lost=value.quantize(product.avg_cost.__class__("0.01")) if with_cost else None,
    )

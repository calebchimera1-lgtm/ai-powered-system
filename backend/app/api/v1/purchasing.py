"""Purchase orders and goods received."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from app.api.deps import Ctx, DbSession, Pagination, require
from app.core.exceptions import PermissionDenied
from app.core.permissions import P
from app.models import Purchase, PurchaseOrder, User
from app.schemas.common import Page
from app.schemas.procurement import (
    GoodsReceivedCreate,
    POCreate,
    POOut,
    PriceChange,
    PurchaseOut,
)
from app.services import procurement_service

router = APIRouter(tags=["Purchasing"])

Reader = Annotated[User, Depends(require(P.PURCHASES_READ))]
Writer = Annotated[User, Depends(require(P.PURCHASES_WRITE))]


class CancelBody(BaseModel):
    reason: str | None = Field(None, max_length=500)


def po_out(po: PurchaseOrder) -> POOut:
    out = POOut.model_validate(po)
    out.total = procurement_service.po_total(po)
    return out


def purchase_out(p: Purchase, price_changes: list[dict] | None = None) -> PurchaseOut:
    out = PurchaseOut.model_validate(p)
    out.po_number = p.purchase_order.po_number if p.purchase_order else None
    changes = price_changes if price_changes is not None else procurement_service.price_changes(p)
    out.price_changes = [PriceChange.model_validate(c) for c in changes]
    return out


def _require_cost(user: User) -> None:
    # Purchasing deals in costs; roles that cannot see costs cannot use it.
    if P.PRODUCTS_VIEW_COST.value not in user.permission_codes:
        raise PermissionDenied("You do not have permission to view purchase costs.")


@router.get("/purchase-orders", response_model=Page[POOut])
def list_orders(
    user: Reader,
    db: DbSession,
    pagination: Pagination,
    status_filter: Annotated[
        Literal["OPEN", "DRAFT", "SENT", "PARTIAL", "RECEIVED", "CANCELLED"] | None,
        Query(alias="status"),
    ] = None,
    supplier_id: int | None = None,
) -> Page[POOut]:
    _require_cost(user)
    rows, total = procurement_service.list_pos(
        db, pagination, status=status_filter, supplier_id=supplier_id
    )
    return Page.build([po_out(po) for po in rows], total, pagination)


@router.post("/purchase-orders", response_model=POOut, status_code=status.HTTP_201_CREATED)
def create_order(body: POCreate, user: Writer, db: DbSession, ctx: Ctx) -> POOut:
    _require_cost(user)
    return po_out(procurement_service.create_po(db, body, user, ctx))


@router.get("/purchase-orders/{po_id}", response_model=POOut)
def get_order(po_id: int, user: Reader, db: DbSession) -> POOut:
    _require_cost(user)
    return po_out(procurement_service.get_po(db, po_id))


@router.put("/purchase-orders/{po_id}", response_model=POOut)
def update_order(po_id: int, body: POCreate, user: Writer, db: DbSession, ctx: Ctx) -> POOut:
    po = procurement_service.get_po(db, po_id)
    return po_out(procurement_service.update_po(db, po, body, user, ctx))


@router.post("/purchase-orders/{po_id}/send", response_model=POOut)
def send_order(po_id: int, user: Writer, db: DbSession, ctx: Ctx) -> POOut:
    """Mark the order as sent to the supplier (by phone, email or in person)."""
    po = procurement_service.get_po(db, po_id)
    return po_out(procurement_service.send_po(db, po, user, ctx))


@router.post("/purchase-orders/{po_id}/cancel", response_model=POOut)
def cancel_order(po_id: int, body: CancelBody, user: Writer, db: DbSession, ctx: Ctx) -> POOut:
    po = procurement_service.get_po(db, po_id)
    return po_out(procurement_service.cancel_po(db, po, user, ctx, body.reason))


@router.get("/purchases", response_model=Page[PurchaseOut])
def list_received(
    user: Reader,
    db: DbSession,
    pagination: Pagination,
    supplier_id: int | None = None,
    search: Annotated[str | None, Query(max_length=50)] = None,
) -> Page[PurchaseOut]:
    _require_cost(user)
    rows, total = procurement_service.list_purchases(
        db, pagination, supplier_id=supplier_id, search=search
    )
    return Page.build([purchase_out(p) for p in rows], total, pagination)


@router.post("/purchases", response_model=PurchaseOut, status_code=status.HTTP_201_CREATED)
def receive(body: GoodsReceivedCreate, user: Writer, db: DbSession, ctx: Ctx) -> PurchaseOut:
    """Record goods received: stock, average cost, batches and supplier prices update."""
    _require_cost(user)
    purchase, changes = procurement_service.receive_goods(db, body, user, ctx)
    return purchase_out(purchase, changes)


@router.get("/purchases/{purchase_id}", response_model=PurchaseOut)
def get_received(purchase_id: int, user: Reader, db: DbSession) -> PurchaseOut:
    _require_cost(user)
    return purchase_out(procurement_service.get_purchase(db, purchase_id))

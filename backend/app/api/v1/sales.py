"""Point of sale, sales history, receipts and customer returns."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import Ctx, CurrentUser, DbSession, Pagination, require
from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.core.permissions import P
from app.models import Sale, SaleReturn, User
from app.schemas.common import Page
from app.schemas.sales import (
    CheckoutRequest,
    ReturnCreate,
    ReturnDecision,
    ReturnItemOut,
    ReturnOut,
    SaleOut,
    SalesSummary,
    StoreInfo,
)
from app.schemas.stock import UserBrief
from app.services import sales_service

router = APIRouter(tags=["Sales"])

Seller = Annotated[User, Depends(require(P.SALES_CREATE))]
SalesReader = Annotated[User, Depends(require(P.SALES_READ_OWN, P.SALES_READ_ALL, any_of=True))]
Returner = Annotated[User, Depends(require(P.RETURNS_REQUEST, P.RETURNS_APPROVE, any_of=True))]
Approver = Annotated[User, Depends(require(P.RETURNS_APPROVE))]


def sale_out(sale: Sale, user: User) -> SaleOut:
    out = SaleOut.model_validate(sale)
    if P.PRODUCTS_VIEW_COST.value in user.permission_codes:
        out.cost_total = sale.cost_total
        net = sale.grand_total - sale.tax_total
        out.gross_profit = net - sale.cost_total
        for item, src in zip(out.items, sale.items, strict=True):
            item.unit_cost = src.unit_cost
    else:
        # Never expose costs to roles without products:view_cost (e.g. cashiers).
        out.cost_total = None
        out.gross_profit = None
        for item in out.items:
            item.unit_cost = None
    return out


def return_out(ret: SaleReturn) -> ReturnOut:
    return ReturnOut(
        id=ret.id,
        return_number=ret.return_number,
        sale_id=ret.sale_id,
        receipt_number=ret.sale.receipt_number,
        status=ret.status,
        reason=ret.reason,
        refund_method=ret.refund_method,
        refund_total=ret.refund_total,
        requested_by=UserBrief.model_validate(ret.requested_by),
        decided_by=UserBrief.model_validate(ret.decided_by) if ret.decided_by else None,
        decided_at=ret.decided_at,
        decision_note=ret.decision_note,
        created_at=ret.created_at,
        items=[
            ReturnItemOut(
                id=i.id,
                sale_item_id=i.sale_item_id,
                product_id=i.sale_item.product_id,
                product_name=i.sale_item.product_name,
                quantity=i.quantity,
                refund_amount=i.refund_amount,
                condition=i.condition,
            )
            for i in ret.items
        ],
    )


@router.get("/store", response_model=StoreInfo, tags=["Settings"])
def store_info(_: CurrentUser) -> StoreInfo:
    """Store details printed on receipts, and the cashier discount limit."""
    s = get_settings()
    return StoreInfo(
        name=s.store_name,
        address=s.store_address,
        phone=s.store_phone,
        kra_pin=s.store_kra_pin,
        receipt_footer=s.receipt_footer,
        currency=s.currency,
        max_cashier_discount_percent=s.max_cashier_discount_percent,
    )


@router.post("/sales", response_model=SaleOut, status_code=status.HTTP_201_CREATED)
def checkout(
    body: CheckoutRequest, user: Seller, db: DbSession, ctx: Ctx, response: Response
) -> SaleOut:
    """Complete a sale: prices come from the catalogue; stock is deducted atomically.

    Re-sending the same `client_request_id` returns the original sale (status 200)."""
    sale, replayed = sales_service.checkout(db, body, user, ctx)
    if replayed:
        response.status_code = status.HTTP_200_OK
    return sale_out(sale, user)


@router.get("/sales", response_model=Page[SaleOut])
def list_sales(
    user: SalesReader,
    db: DbSession,
    pagination: Pagination,
    date_from: date | None = None,
    date_to: date | None = None,
    cashier_id: int | None = None,
    payment_method: Literal["CASH", "MPESA", "CARD"] | None = None,
    search: Annotated[str | None, Query(max_length=40)] = None,
) -> Page[SaleOut]:
    """Cashiers see only their own sales."""
    rows, total = sales_service.list_sales(
        db,
        pagination,
        user,
        date_from=date_from,
        date_to=date_to,
        cashier_id=cashier_id,
        payment_method=payment_method,
        search=search,
    )
    return Page.build([sale_out(s, user) for s in rows], total, pagination)


@router.get("/sales/summary", response_model=SalesSummary)
def sales_summary(
    user: SalesReader,
    db: DbSession,
    date_from: date | None = None,
    date_to: date | None = None,
    cashier_id: int | None = None,
) -> SalesSummary:
    """Totals by payment method, e.g. for the end-of-day cash-up."""
    return SalesSummary.model_validate(
        sales_service.summary(db, user, date_from=date_from, date_to=date_to, cashier_id=cashier_id)
    )


@router.get("/sales/by-receipt/{receipt_number}", response_model=SaleOut)
def by_receipt(receipt_number: str, user: Returner, db: DbSession) -> SaleOut:
    return sale_out(sales_service.find_by_receipt(db, receipt_number, user), user)


@router.get("/sales/{sale_id}", response_model=SaleOut)
def get_sale(sale_id: int, user: SalesReader, db: DbSession) -> SaleOut:
    return sale_out(sales_service.get_sale(db, sale_id, user), user)


@router.post(
    "/sales/{sale_id}/returns", response_model=ReturnOut, status_code=status.HTTP_201_CREATED
)
def create_return(
    sale_id: int, body: ReturnCreate, user: Returner, db: DbSession, ctx: Ctx
) -> ReturnOut:
    """Return items from a receipt. Cashiers' returns wait for a manager's approval."""
    sale = db.get(Sale, sale_id)
    if sale is None:
        raise NotFoundError("Sale not found")
    ret, _ = sales_service.create_return(db, sale, body, user, ctx)
    return return_out(ret)


@router.get("/returns", response_model=Page[ReturnOut], tags=["Returns"])
def list_returns(
    user: Returner,
    db: DbSession,
    pagination: Pagination,
    status_filter: Annotated[
        Literal["PENDING", "APPROVED", "REJECTED"] | None, Query(alias="status")
    ] = None,
    sale_id: int | None = None,
) -> Page[ReturnOut]:
    rows, total = sales_service.list_returns(
        db, pagination, user, status=status_filter, sale_id=sale_id
    )
    return Page.build([return_out(r) for r in rows], total, pagination)


@router.post("/returns/{return_id}/approve", response_model=ReturnOut, tags=["Returns"])
def approve_return(
    return_id: int, body: ReturnDecision, user: Approver, db: DbSession, ctx: Ctx
) -> ReturnOut:
    ret = sales_service.get_return(db, return_id)
    return return_out(sales_service.approve_return(db, ret, user, ctx, body.note))


@router.post("/returns/{return_id}/reject", response_model=ReturnOut, tags=["Returns"])
def reject_return(
    return_id: int, body: ReturnDecision, user: Approver, db: DbSession, ctx: Ctx
) -> ReturnOut:
    ret = sales_service.get_return(db, return_id)
    return return_out(sales_service.reject_return(db, ret, user, ctx, body.note))

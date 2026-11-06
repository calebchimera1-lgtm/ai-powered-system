"""Point of sale: checkout, sales history and customer returns.

Checkout is one database transaction: the sale, its lines, every stock deduction and the
customer record either all commit or none do. Lines are processed in product-id order so
two tills selling the same products lock rows in the same order and cannot deadlock.
"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDenied,
    ValidationFailed,
)
from app.core.permissions import P
from app.models import (
    Customer,
    Product,
    Sale,
    SaleItem,
    SaleReturn,
    SaleReturnItem,
    StockMovement,
    User,
)
from app.schemas.common import PageParams
from app.schemas.sales import CheckoutRequest, ReturnCreate
from app.services import audit_service, inventory_service, numbering
from app.services.audit_service import RequestContext
from app.services.inventory_service import fmt
from app.services.pricing import LineInput, PricingError, price_cart, proportional_refund

ZERO = Decimal("0")
CENT = Decimal("0.01")


def _now() -> datetime:
    return datetime.now(UTC)


def _has(user: User, perm: P) -> bool:
    return perm.value in user.permission_codes


# --- Checkout --------------------------------------------------------------------


def checkout(
    db: Session,
    data: CheckoutRequest,
    cashier: User,
    ctx: RequestContext,
    *,
    sold_at: datetime | None = None,  # historical imports/demo data only; never from the API
) -> tuple[Sale, bool]:
    """Record a sale. Returns (sale, replayed); replayed=True if this request id was
    already processed (e.g. the till retried after a network drop)."""
    existing = db.scalar(select(Sale).where(Sale.client_request_id == data.client_request_id))
    if existing is not None:
        if existing.cashier_id != cashier.id:
            raise ConflictError("This sale request id was already used")
        return existing, True

    settings = get_settings()
    # Load products in id order (consistent locking order across tills).
    ids = sorted({line.product_id for line in data.items})
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(ids)))}
    for pid in ids:
        p = products.get(pid)
        if p is None or not p.is_active:
            raise ValidationFailed(f"Product {pid} is not available for sale")

    inputs = [
        LineInput(
            quantity=line.quantity,
            unit_price=products[line.product_id].selling_price,
            vat_rate=products[line.product_id].vat_rate,
            line_discount=line.discount,
        )
        for line in data.items
    ]
    for line in data.items:
        inventory_service.validate_quantity(products[line.product_id], line.quantity)
    try:
        cart = price_cart(inputs, data.cart_discount)
    except PricingError as exc:
        raise ValidationFailed(str(exc)) from exc

    if cart.discount_total > 0 and cart.discount_percent > settings.max_cashier_discount_percent:
        if not _has(cashier, P.SALES_DISCOUNT_ANY):
            raise PermissionDenied(
                f"Discounts above {fmt(settings.max_cashier_discount_percent)}% need a Store "
                f"Manager (this sale: {cart.discount_percent}%).",
                code="DISCOUNT_LIMIT",
            )

    tendered = change = None
    if data.payment_method == "CASH":
        tendered = data.amount_tendered
        if tendered is None or tendered < cart.grand_total:
            raise ValidationFailed(
                f"Cash received must be at least KES {cart.grand_total:,.2f}",
                details=[{"field": "amount_tendered", "message": "less than the total"}],
            )
        change = (tendered - cart.grand_total).quantize(CENT)

    customer = _customer(db, data.customer_name, data.customer_phone)

    sale = Sale(
        receipt_number=numbering.next_number(db, "sale"),
        client_request_id=data.client_request_id,
        cashier_id=cashier.id,
        customer_id=customer.id if customer else None,
        subtotal=cart.subtotal,
        discount_total=cart.discount_total,
        tax_total=cart.tax_total,
        grand_total=cart.grand_total,
        cost_total=ZERO,
        payment_method=data.payment_method,
        payment_reference=data.payment_reference if data.payment_method != "CASH" else None,
        amount_tendered=tendered,
        change_given=change,
        notes=(data.notes or "").strip() or None,
    )
    if sold_at is not None:
        sale.sold_at = sold_at
    db.add(sale)
    db.flush()

    # Deduct stock in product-id order; keep the cart order for the receipt lines.
    order = sorted(range(len(data.items)), key=lambda i: data.items[i].product_id)
    items: list[SaleItem | None] = [None] * len(data.items)
    cost_total = ZERO
    for i in order:
        line, priced = data.items[i], cart.lines[i]
        product = products[line.product_id]
        movements = inventory_service.apply_movement(
            db,
            product_id=product.id,
            quantity=-line.quantity,
            movement_type="SALE_OUT",
            user=cashier,
            reference_type="sale",
            reference_id=sale.id,
            reason=sale.receipt_number,
            occurred_at=sold_at,
        )
        unit_cost = movements[0].unit_cost
        cost_total += line.quantity * unit_cost
        items[i] = SaleItem(
            product_id=product.id,
            product_name=product.name,
            quantity=line.quantity,
            unit_price=product.selling_price,
            discount_amount=priced.discount,
            vat_rate=product.vat_rate,
            tax_amount=priced.tax,
            line_total=priced.total,
            unit_cost=unit_cost,
        )
    sale.items = [item for item in items if item is not None]
    sale.cost_total = cost_total.quantize(CENT, ROUND_HALF_UP)

    if cart.discount_percent > settings.max_cashier_discount_percent:
        audit_service.record(
            db,
            action="sale.discount_override",
            actor=cashier,
            ctx=ctx,
            entity_type="sale",
            entity_id=sale.id,
            after={"discount_kes": cart.discount_total, "percent": cart.discount_percent},
        )
    db.commit()
    db.refresh(sale)
    return sale, False


def _customer(db: Session, name: str | None, phone: str | None) -> Customer | None:
    name = (name or "").strip()
    if not phone and not name:
        return None
    if phone:
        existing = db.scalar(select(Customer).where(Customer.phone == phone))
        if existing:
            if name and existing.name != name:
                existing.name = name
            return existing
    customer = Customer(name=name or "Walk-in customer", phone=phone)
    db.add(customer)
    db.flush()
    return customer


# --- Queries ---------------------------------------------------------------------


def get_sale(db: Session, sale_id: int, user: User) -> Sale:
    sale = db.get(Sale, sale_id)
    if sale is None or not can_view(user, sale):
        raise NotFoundError("Sale not found")
    return sale


def can_view(user: User, sale: Sale) -> bool:
    return _has(user, P.SALES_READ_ALL) or (
        _has(user, P.SALES_READ_OWN) and sale.cashier_id == user.id
    )


def find_by_receipt(db: Session, receipt_number: str, user: User) -> Sale:
    sale = db.scalar(
        select(Sale).where(func.upper(Sale.receipt_number) == receipt_number.strip().upper())
    )
    if sale is None or not can_view(user, sale):
        raise NotFoundError("No sale with that receipt number")
    return sale


def _day_bounds(date_from: date | None, date_to: date | None) -> tuple[datetime | None, ...]:
    tz = ZoneInfo(get_settings().store_timezone)
    start = datetime.combine(date_from, time.min, tz) if date_from else None
    end = datetime.combine(date_to + timedelta(days=1), time.min, tz) if date_to else None
    return start, end


def _scoped(stmt, user: User, cashier_id: int | None):  # type: ignore[no-untyped-def]
    if not _has(user, P.SALES_READ_ALL):
        return stmt.where(Sale.cashier_id == user.id)  # cashiers see only their own
    if cashier_id:
        return stmt.where(Sale.cashier_id == cashier_id)
    return stmt


def list_sales(
    db: Session,
    params: PageParams,
    user: User,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    cashier_id: int | None = None,
    payment_method: str | None = None,
    search: str | None = None,
) -> tuple[list[Sale], int]:
    stmt = _scoped(select(Sale), user, cashier_id)
    start, end = _day_bounds(date_from, date_to)
    if start:
        stmt = stmt.where(Sale.sold_at >= start)
    if end:
        stmt = stmt.where(Sale.sold_at < end)
    if payment_method:
        stmt = stmt.where(Sale.payment_method == payment_method)
    if search:
        term = f"%{search.strip().upper()}%"
        stmt = stmt.where(
            func.upper(Sale.receipt_number).like(term)
            | func.upper(func.coalesce(Sale.payment_reference, "")).like(term)
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Sale.sold_at.desc(), Sale.id.desc())
        .offset(params.offset)
        .limit(params.page_size)
    ).all()
    return list(rows), total


def summary(
    db: Session,
    user: User,
    *,
    date_from: date | None,
    date_to: date | None,
    cashier_id: int | None = None,
) -> dict:
    """Totals per payment method (end-of-day cash-up)."""
    start, end = _day_bounds(date_from, date_to)
    stmt = select(
        Sale.payment_method,
        func.count(Sale.id),
        func.coalesce(func.sum(Sale.grand_total), 0),
        func.coalesce(func.sum(Sale.discount_total), 0),
        func.coalesce(func.sum(Sale.tax_total), 0),
    ).group_by(Sale.payment_method)
    stmt = _scoped(stmt, user, cashier_id)
    if start:
        stmt = stmt.where(Sale.sold_at >= start)
    if end:
        stmt = stmt.where(Sale.sold_at < end)
    rows = db.execute(stmt).all()

    refunds = select(func.coalesce(func.sum(SaleReturn.refund_total), 0)).where(
        SaleReturn.status == "APPROVED"
    )
    if start:
        refunds = refunds.where(SaleReturn.decided_at >= start)
    if end:
        refunds = refunds.where(SaleReturn.decided_at < end)
    if not _has(user, P.SALES_READ_ALL):
        refunds = refunds.where(SaleReturn.requested_by_id == user.id)
    elif cashier_id:
        refunds = refunds.where(SaleReturn.requested_by_id == cashier_id)

    return {
        "count": sum(r[1] for r in rows),
        "gross_total": sum((Decimal(r[2]) for r in rows), ZERO),
        "discount_total": sum((Decimal(r[3]) for r in rows), ZERO),
        "tax_total": sum((Decimal(r[4]) for r in rows), ZERO),
        "refunds_total": Decimal(db.scalar(refunds) or 0),
        "by_method": [
            {"payment_method": r[0], "count": r[1], "total": Decimal(r[2])} for r in rows
        ],
    }


# --- Returns ----------------------------------------------------------------------


def _pending_return_qty(db: Session, sale_item_id: int) -> tuple[Decimal, Decimal]:
    """(quantity, refund) already claimed by PENDING returns for this line."""
    row = db.execute(
        select(
            func.coalesce(func.sum(SaleReturnItem.quantity), 0),
            func.coalesce(func.sum(SaleReturnItem.refund_amount), 0),
        )
        .join(SaleReturn, SaleReturn.id == SaleReturnItem.return_id)
        .where(SaleReturnItem.sale_item_id == sale_item_id, SaleReturn.status == "PENDING")
    ).one()
    return Decimal(row[0]), Decimal(row[1])


def _refunded(db: Session, sale_item_id: int) -> Decimal:
    return Decimal(
        db.scalar(
            select(func.coalesce(func.sum(SaleReturnItem.refund_amount), 0))
            .join(SaleReturn, SaleReturn.id == SaleReturnItem.return_id)
            .where(SaleReturnItem.sale_item_id == sale_item_id, SaleReturn.status == "APPROVED")
        )
        or 0
    )


def create_return(
    db: Session,
    sale: Sale,
    data: ReturnCreate,
    user: User,
    ctx: RequestContext,
    *,
    at: datetime | None = None,  # historical imports/demo data only
) -> tuple[SaleReturn, bool]:
    """Record a customer return. Approvers' returns apply immediately; others wait."""
    if not can_view(user, sale) and not _has(user, P.RETURNS_APPROVE):
        raise NotFoundError("Sale not found")
    by_id = {item.id: item for item in sale.items}
    seen: set[int] = set()
    lines: list[SaleReturnItem] = []
    for line in data.items:
        item = by_id.get(line.sale_item_id)
        if item is None:
            raise ValidationFailed("That item is not on this receipt")
        if line.sale_item_id in seen:
            raise ValidationFailed(f"{item.product_name} is listed twice")
        seen.add(line.sale_item_id)
        inventory_service.validate_quantity(item.product, line.quantity)
        pending_qty, pending_refund = _pending_return_qty(db, item.id)
        already = item.returned_quantity + pending_qty
        available = item.quantity - already
        if line.quantity > available:
            raise ValidationFailed(
                f"Only {fmt(available)} of {item.product_name} can still be returned "
                f"({fmt(item.quantity)} sold, {fmt(already)} already returned or pending)."
            )
        refund = proportional_refund(
            item.line_total,
            item.quantity,
            already,
            _refunded(db, item.id) + pending_refund,
            line.quantity,
        )
        lines.append(
            SaleReturnItem(
                sale_item_id=item.id,
                quantity=line.quantity,
                refund_amount=refund,
                condition=line.condition,
            )
        )

    ret = SaleReturn(
        return_number=numbering.next_number(db, "return"),
        sale_id=sale.id,
        status="PENDING",
        reason=data.reason.strip(),
        refund_method=data.refund_method,
        refund_total=sum((li.refund_amount for li in lines), ZERO),
        requested_by_id=user.id,
        items=lines,
    )
    if at is not None:
        ret.created_at = at
    db.add(ret)
    db.flush()
    applied = _has(user, P.RETURNS_APPROVE)
    if applied:
        _apply_return(db, ret, user, note="Approved at the counter", at=at)
    audit_service.record(
        db,
        action="return.approved" if applied else "return.requested",
        actor=user,
        ctx=ctx,
        entity_type="sale_return",
        entity_id=ret.id,
        after={"receipt": sale.receipt_number, "refund_kes": ret.refund_total, "items": len(lines)},
        details=ret.reason,
    )
    db.commit()
    db.refresh(ret)
    return ret, applied


def _apply_return(
    db: Session, ret: SaleReturn, user: User, *, note: str | None, at: datetime | None = None
) -> None:
    sale = db.scalar(select(Sale).where(Sale.id == ret.sale_id).with_for_update(of=Sale))
    assert sale is not None
    for line in ret.items:
        item = db.scalar(
            select(SaleItem).where(SaleItem.id == line.sale_item_id).with_for_update(of=SaleItem)
        )
        assert item is not None
        if item.returned_quantity + line.quantity > item.quantity:
            raise ValidationFailed(f"{item.product_name}: more returned than was sold")
        item.returned_quantity += line.quantity
        if line.condition == "RESALEABLE":
            # Back on the shelf at the cost it left with, into the batch it came from.
            batch_id = db.scalar(
                select(StockMovement.batch_id)
                .where(
                    StockMovement.reference_type == "sale",
                    StockMovement.reference_id == str(sale.id),
                    StockMovement.product_id == item.product_id,
                    StockMovement.batch_id.is_not(None),
                )
                .order_by(StockMovement.id.desc())
                .limit(1)
            )
            inventory_service.apply_movement(
                db,
                product_id=item.product_id,
                quantity=line.quantity,
                movement_type="RETURN_IN",
                user=user,
                unit_cost=item.unit_cost,
                batch_id=batch_id,
                reference_type="sale_return",
                reference_id=ret.id,
                reason=f"{ret.return_number} (receipt {sale.receipt_number})",
                require_expiry=False,
                occurred_at=at,
            )
        # DAMAGED returns never re-enter stock; their cost counts as a stock loss.
    returned = sum((i.returned_quantity for i in sale.items), ZERO)
    sold = sum((i.quantity for i in sale.items), ZERO)
    sale.status = "RETURNED" if returned >= sold else "PARTIALLY_RETURNED"
    ret.status = "APPROVED"
    ret.decided_by_id = user.id
    ret.decided_at = at or _now()
    ret.decision_note = note


def get_return(db: Session, return_id: int) -> SaleReturn:
    ret = db.get(SaleReturn, return_id)
    if ret is None:
        raise NotFoundError("Return not found")
    return ret


def approve_return(
    db: Session, ret: SaleReturn, user: User, ctx: RequestContext, note: str | None
) -> SaleReturn:
    if ret.status != "PENDING":
        raise ValidationFailed(f"This return is already {ret.status.lower()}")
    if ret.requested_by_id == user.id:
        raise PermissionDenied("Someone else must approve your own return request.")
    _apply_return(db, ret, user, note=(note or "").strip() or None)
    audit_service.record(
        db,
        action="return.approved",
        actor=user,
        ctx=ctx,
        entity_type="sale_return",
        entity_id=ret.id,
        after={"refund_kes": ret.refund_total},
    )
    db.commit()
    db.refresh(ret)
    return ret


def reject_return(
    db: Session, ret: SaleReturn, user: User, ctx: RequestContext, note: str | None
) -> SaleReturn:
    if ret.status != "PENDING":
        raise ValidationFailed(f"This return is already {ret.status.lower()}")
    if not (note or "").strip():
        raise ValidationFailed(
            "Please give a reason for rejecting", details=[{"field": "note", "message": "required"}]
        )
    ret.status = "REJECTED"
    ret.decided_by_id = user.id
    ret.decided_at = _now()
    ret.decision_note = note.strip()  # type: ignore[union-attr]
    audit_service.record(
        db,
        action="return.rejected",
        actor=user,
        ctx=ctx,
        entity_type="sale_return",
        entity_id=ret.id,
        details=ret.decision_note,
    )
    db.commit()
    db.refresh(ret)
    return ret


def list_returns(
    db: Session, params: PageParams, user: User, *, status: str | None, sale_id: int | None
) -> tuple[list[SaleReturn], int]:
    stmt = select(SaleReturn)
    if not (_has(user, P.RETURNS_APPROVE) or _has(user, P.SALES_READ_ALL)):
        stmt = stmt.where(SaleReturn.requested_by_id == user.id)
    if status:
        stmt = stmt.where(SaleReturn.status == status)
    if sale_id:
        stmt = stmt.where(SaleReturn.sale_id == sale_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(SaleReturn.created_at.desc(), SaleReturn.id.desc())
        .offset(params.offset)
        .limit(params.page_size)
    ).all()
    return list(rows), total

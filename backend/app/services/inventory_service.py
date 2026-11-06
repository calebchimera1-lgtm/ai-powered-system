"""The single entry point for changing stock.

Every stock change (opening stock, purchases, sales, returns, write-offs, adjustments)
calls `apply_movement`. It:

1. locks the product row (SELECT ... FOR UPDATE) so concurrent changes queue up,
2. validates the quantity for the product's unit of measure,
3. refuses to go below zero unless `allow_negative` is passed (callers must check the
   `stock:adjust_negative` permission before passing it),
4. updates the weighted average cost (WAC) on stock received with a cost,
5. updates batches: creates/extends one on receipt, deducts FEFO (first-expiry-first-out)
   on removal,
6. appends one ledger row per batch slice to `stock_movements`, with the running balance.

It does not commit: the caller's transaction decides, so a sale or invoice approval
either fully succeeds or leaves no trace.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationFailed
from app.models import Product, ProductBatch, StockMovement, User
from app.models.catalog import COUNT_UNITS
from app.models.stock import INBOUND_TYPES, OUTBOUND_TYPES

ZERO = Decimal("0")
QTY_PLACES = Decimal("0.001")
COST_PLACES = Decimal("0.0001")

# Inbound movement types that bring stock in at a new cost and therefore change the WAC.
COSTED_INBOUND = ("OPENING", "PURCHASE_IN")


class InsufficientStock(ConflictError):
    code = "INSUFFICIENT_STOCK"


@dataclass(frozen=True)
class BatchInfo:
    batch_number: str | None = None
    expiry_date: date | None = None


def q(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(QTY_PLACES, rounding=ROUND_HALF_UP)


def weighted_average_cost(
    on_hand: Decimal, current_avg: Decimal, qty_in: Decimal, unit_cost: Decimal
) -> Decimal:
    """WAC after receiving `qty_in` at `unit_cost`.

    If stock was zero or negative (e.g. sold ahead of a delivery), the old cost no longer
    describes anything on the shelf, so the new cost is the delivery's cost.
    """
    if qty_in <= 0:
        raise ValueError("qty_in must be positive")
    if on_hand <= 0:
        return unit_cost.quantize(COST_PLACES, rounding=ROUND_HALF_UP)
    total = on_hand * current_avg + qty_in * unit_cost
    return (total / (on_hand + qty_in)).quantize(COST_PLACES, rounding=ROUND_HALF_UP)


def lock_product(db: Session, product_id: int) -> Product:
    # Write the caller's pending changes first: the refresh below would otherwise discard them.
    db.flush()
    product = db.scalar(select(Product).where(Product.id == product_id).with_for_update(of=Product))
    if product is None:
        raise NotFoundError("Product not found")
    db.refresh(product)  # make sure we see the latest committed balance under the lock
    return product


def validate_quantity(product: Product, quantity: Decimal) -> Decimal:
    quantity = q(quantity)
    if quantity == 0:
        raise ValidationFailed("Quantity must not be zero")
    if product.unit_of_measure in COUNT_UNITS and quantity != quantity.to_integral_value():
        raise ValidationFailed(
            f"{product.name} is counted in whole {product.unit_of_measure}; " "use a whole number"
        )
    return quantity


def apply_movement(
    db: Session,
    *,
    product_id: int,
    quantity: Decimal,
    movement_type: str,
    user: User,
    unit_cost: Decimal | None = None,
    batch_id: int | None = None,
    batch_info: BatchInfo | None = None,
    reference_type: str | None = None,
    reference_id: str | int | None = None,
    reason: str | None = None,
    allow_negative: bool = False,
    require_expiry: bool = True,
    occurred_at: datetime | None = None,
) -> list[StockMovement]:
    """Apply a signed stock change. Positive = stock in, negative = stock out."""
    product = lock_product(db, product_id)
    quantity = validate_quantity(product, Decimal(quantity))

    if movement_type in INBOUND_TYPES and quantity < 0:
        raise ValidationFailed(f"{movement_type} must increase stock")
    if movement_type in OUTBOUND_TYPES and quantity > 0:
        raise ValidationFailed(f"{movement_type} must decrease stock")
    if movement_type not in INBOUND_TYPES + OUTBOUND_TYPES:
        raise ValidationFailed(f"Unknown movement type {movement_type}")

    ref_id = str(reference_id) if reference_id is not None else None
    common: dict = {
        "product_id": product.id,
        "movement_type": movement_type,
        "user_id": user.id,
        "reference_type": reference_type,
        "reference_id": ref_id,
        "reason": reason,
    }
    if occurred_at is not None:  # only for importing/seeding historical records
        common["created_at"] = occurred_at
    if quantity > 0:
        return [
            _receive(db, product, quantity, unit_cost, batch_id, batch_info, common, require_expiry)
        ]
    return _remove(db, product, -quantity, batch_id, allow_negative, common)


def _receive(
    db: Session,
    product: Product,
    qty: Decimal,
    unit_cost: Decimal | None,
    batch_id: int | None,
    batch_info: BatchInfo | None,
    common: dict,
    require_expiry: bool = True,
) -> StockMovement:
    movement_type = common["movement_type"]
    if unit_cost is None:
        if movement_type in COSTED_INBOUND:
            raise ValidationFailed("A unit cost is required when receiving stock")
        unit_cost = product.avg_cost  # found stock / customer returns are valued at WAC
    unit_cost = Decimal(unit_cost).quantize(COST_PLACES, rounding=ROUND_HALF_UP)
    if unit_cost < 0:
        raise ValidationFailed("Unit cost cannot be negative")

    batch = _batch_for_receipt(db, product, qty, unit_cost, batch_id, batch_info, require_expiry)

    product.avg_cost = weighted_average_cost(
        product.quantity_on_hand, product.avg_cost, qty, unit_cost
    )
    if movement_type in COSTED_INBOUND:
        product.purchase_price = unit_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    product.quantity_on_hand = q(product.quantity_on_hand + qty)

    movement = StockMovement(
        **common,
        batch_id=batch.id if batch else None,
        quantity=qty,
        unit_cost=unit_cost,
        balance_after=product.quantity_on_hand,
    )
    db.add(movement)
    db.flush()
    return movement


def _batch_for_receipt(
    db: Session,
    product: Product,
    qty: Decimal,
    unit_cost: Decimal,
    batch_id: int | None,
    info: BatchInfo | None,
    require_expiry: bool = True,
) -> ProductBatch | None:
    if batch_id is not None:
        batch = db.get(ProductBatch, batch_id, with_for_update=True)
        if batch is None or batch.product_id != product.id:
            raise ValidationFailed("That batch does not belong to this product")
        batch.quantity_received = q(batch.quantity_received + qty)
        batch.quantity_remaining = q(batch.quantity_remaining + qty)
        return batch

    info = info or BatchInfo()
    # require_expiry=False is used for customer returns whose original batch is unknown.
    if product.tracks_expiry and info.expiry_date is None and require_expiry:
        raise ValidationFailed(
            f"{product.name} tracks expiry dates; enter the expiry date for this stock",
            details=[{"field": "expiry_date", "message": "required for this product"}],
        )
    if info.expiry_date is None and not info.batch_number:
        return None  # untracked stock

    batch_number = info.batch_number.strip() if info.batch_number else None
    existing = db.scalar(
        select(ProductBatch)
        .where(
            ProductBatch.product_id == product.id,
            ProductBatch.batch_number.is_not_distinct_from(batch_number),
            ProductBatch.expiry_date.is_not_distinct_from(info.expiry_date),
            ProductBatch.unit_cost == unit_cost,
        )
        .with_for_update()
    )
    if existing:
        existing.quantity_received = q(existing.quantity_received + qty)
        existing.quantity_remaining = q(existing.quantity_remaining + qty)
        return existing
    batch = ProductBatch(
        product_id=product.id,
        batch_number=batch_number,
        expiry_date=info.expiry_date,
        quantity_received=qty,
        quantity_remaining=qty,
        unit_cost=unit_cost,
    )
    db.add(batch)
    db.flush()
    return batch


def _remove(
    db: Session,
    product: Product,
    qty: Decimal,
    batch_id: int | None,
    allow_negative: bool,
    common: dict,
) -> list[StockMovement]:
    new_balance = q(product.quantity_on_hand - qty)
    if new_balance < 0 and not allow_negative:
        raise InsufficientStock(
            f"Not enough stock of {product.name}: {fmt(product.quantity_on_hand)} "
            f"{product.unit_of_measure} available, {fmt(qty)} requested.",
            details={"available": str(product.quantity_on_hand), "requested": str(qty)},
        )

    # Work out which batches the stock comes from.
    slices: list[tuple[ProductBatch | None, Decimal]] = []
    if batch_id is not None:
        batch = db.get(ProductBatch, batch_id, with_for_update=True)
        if batch is None or batch.product_id != product.id:
            raise ValidationFailed("That batch does not belong to this product")
        if batch.quantity_remaining < qty:
            raise InsufficientStock(
                f"Batch {batch.batch_number or batch.id} has only "
                f"{fmt(batch.quantity_remaining)} {product.unit_of_measure} left."
            )
        slices.append((batch, qty))
    else:
        remaining = qty
        for batch in fefo_batches(db, product.id):
            if remaining <= 0:
                break
            take = min(batch.quantity_remaining, remaining)
            slices.append((batch, take))
            remaining -= take
        if remaining > 0:
            slices.append((None, remaining))  # untracked (or negative) stock

    movements = []
    cost = product.avg_cost
    balance = product.quantity_on_hand
    for batch, take in slices:
        if batch is not None:
            batch.quantity_remaining = q(batch.quantity_remaining - take)
        balance = q(balance - take)
        movement = StockMovement(
            **common,
            batch_id=batch.id if batch else None,
            quantity=-take,
            unit_cost=cost,
            balance_after=balance,
        )
        db.add(movement)
        movements.append(movement)
    product.quantity_on_hand = balance
    db.flush()
    return movements


def fefo_batches(db: Session, product_id: int) -> list[ProductBatch]:
    """Batches with stock left, earliest expiry first (no-expiry batches last), locked."""
    return list(
        db.scalars(
            select(ProductBatch)
            .where(ProductBatch.product_id == product_id, ProductBatch.quantity_remaining > 0)
            .order_by(
                ProductBatch.expiry_date.asc().nulls_last(),
                ProductBatch.received_at,
                ProductBatch.id,
            )
            .with_for_update()
        )
    )


def ledger_balance(db: Session, product_id: int) -> Decimal:
    """Sum of all movements: must always equal products.quantity_on_hand."""
    total = db.scalar(
        select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
            StockMovement.product_id == product_id
        )
    )
    return q(total)


def fmt(value: Decimal) -> str:
    """1.000 -> '1', 2.500 -> '2.5'."""
    text = f"{Decimal(value).normalize():f}"
    return text

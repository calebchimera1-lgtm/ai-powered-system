"""Purchase orders and goods received.

`receive_goods` is the single path by which supplier stock enters the shop. Phase 4's
invoice approval calls it too, so manual receipts and digitized invoices follow the same
rules: one transaction that records the receipt, increases stock at the new cost
(updating the weighted average cost), records batches/expiry, updates the supplier's last
price, flags price changes, and advances the purchase order.
"""

from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailed
from app.models import (
    Product,
    Purchase,
    PurchaseItem,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
    SupplierProduct,
    User,
)
from app.schemas.common import PageParams
from app.schemas.procurement import GoodsReceivedCreate, POCreate
from app.services import audit_service, inventory_service, numbering
from app.services.audit_service import RequestContext
from app.services.pricing import money, vat_on_top

ZERO = Decimal("0")


def _supplier(db: Session, supplier_id: int) -> Supplier:
    sup = db.get(Supplier, supplier_id)
    if sup is None:
        raise ValidationFailed(
            "Supplier not found", details=[{"field": "supplier_id", "message": "not found"}]
        )
    if not sup.is_active:
        raise ValidationFailed(f"{sup.name} is deactivated")
    return sup


def _products(db: Session, ids: list[int]) -> dict[int, Product]:
    found = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(ids)))}
    for pid in ids:
        if pid not in found:
            raise ValidationFailed(f"Product {pid} not found")
        if not found[pid].is_active:
            raise ValidationFailed(f"{found[pid].name} is deactivated")
    return found


def po_total(po: PurchaseOrder) -> Decimal:
    return money(sum((i.quantity_ordered * i.unit_cost for i in po.items), ZERO))


def price_changes(purchase: Purchase) -> list[dict[str, Any]]:
    """Lines whose cost moved by at least the alert threshold versus the previous cost.

    Derived from the stored lines, so a delivery shows its price changes whenever it is
    viewed, not only at the moment it was received."""
    threshold = get_settings().price_change_alert_percent
    out = []
    for item in purchase.items:
        prev = item.previous_unit_cost
        if prev is None or prev == 0:
            continue
        pct = ((item.unit_cost - prev) / prev * 100).quantize(Decimal("0.01"))
        if abs(pct) >= threshold:
            out.append(
                {
                    "product_id": item.product_id,
                    "product_name": item.product.name,
                    "previous_unit_cost": prev,
                    "new_unit_cost": item.unit_cost,
                    "change_percent": pct,
                }
            )
    return out


# --- Purchase orders ---------------------------------------------------------------


def create_po(db: Session, data: POCreate, user: User, ctx: RequestContext) -> PurchaseOrder:
    sup = _supplier(db, data.supplier_id)
    products = _products(db, [i.product_id for i in data.items])
    for line in data.items:
        inventory_service.validate_quantity(products[line.product_id], line.quantity)
    po = PurchaseOrder(
        po_number=numbering.next_number(db, "purchase_order"),
        supplier_id=sup.id,
        status="DRAFT",
        order_date=date.today(),
        expected_date=data.expected_date,
        notes=(data.notes or "").strip() or None,
        created_by_id=user.id,
        items=[
            PurchaseOrderItem(
                product_id=line.product_id,
                quantity_ordered=line.quantity,
                unit_cost=money(line.unit_cost),
            )
            for line in data.items
        ],
    )
    db.add(po)
    db.flush()
    audit_service.record(
        db,
        action="purchase_order.create",
        actor=user,
        ctx=ctx,
        entity_type="purchase_order",
        entity_id=po.id,
        after={"supplier": sup.name, "lines": len(po.items), "total_kes": po_total(po)},
    )
    db.commit()
    db.refresh(po)
    return po


def get_po(db: Session, po_id: int) -> PurchaseOrder:
    po = db.get(PurchaseOrder, po_id)
    if po is None:
        raise NotFoundError("Purchase order not found")
    return po


def update_po(
    db: Session, po: PurchaseOrder, data: POCreate, user: User, ctx: RequestContext
) -> PurchaseOrder:
    if po.status != "DRAFT":
        raise ValidationFailed("Only draft orders can be edited")
    sup = _supplier(db, data.supplier_id)
    products = _products(db, [i.product_id for i in data.items])
    for line in data.items:
        inventory_service.validate_quantity(products[line.product_id], line.quantity)
    po.supplier_id = sup.id
    po.expected_date = data.expected_date
    po.notes = (data.notes or "").strip() or None
    po.items.clear()
    db.flush()
    po.items.extend(
        PurchaseOrderItem(
            product_id=line.product_id,
            quantity_ordered=line.quantity,
            unit_cost=money(line.unit_cost),
        )
        for line in data.items
    )
    audit_service.record(
        db,
        action="purchase_order.update",
        actor=user,
        ctx=ctx,
        entity_type="purchase_order",
        entity_id=po.id,
    )
    db.commit()
    db.refresh(po)
    return po


def send_po(db: Session, po: PurchaseOrder, user: User, ctx: RequestContext) -> PurchaseOrder:
    if po.status != "DRAFT":
        raise ValidationFailed("Only draft orders can be marked as sent")
    po.status = "SENT"
    po.sent_at = datetime.now(UTC)
    audit_service.record(
        db,
        action="purchase_order.sent",
        actor=user,
        ctx=ctx,
        entity_type="purchase_order",
        entity_id=po.id,
    )
    db.commit()
    db.refresh(po)
    return po


def cancel_po(
    db: Session, po: PurchaseOrder, user: User, ctx: RequestContext, reason: str | None
) -> PurchaseOrder:
    if po.status in ("RECEIVED", "CANCELLED"):
        raise ValidationFailed(f"This order is already {po.status.lower()}")
    po.status = "CANCELLED"
    audit_service.record(
        db,
        action="purchase_order.cancelled",
        actor=user,
        ctx=ctx,
        entity_type="purchase_order",
        entity_id=po.id,
        details=reason,
    )
    db.commit()
    db.refresh(po)
    return po


def list_pos(
    db: Session, params: PageParams, *, status: str | None, supplier_id: int | None
) -> tuple[list[PurchaseOrder], int]:
    stmt = select(PurchaseOrder)
    if status == "OPEN":
        stmt = stmt.where(PurchaseOrder.status.in_(["DRAFT", "SENT", "PARTIAL"]))
    elif status:
        stmt = stmt.where(PurchaseOrder.status == status)
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc())
        .offset(params.offset)
        .limit(params.page_size)
    ).all()
    return list(rows), total


# --- Goods received ------------------------------------------------------------------


def receive_goods(
    db: Session,
    data: GoodsReceivedCreate,
    user: User,
    ctx: RequestContext,
    *,
    source: str = "MANUAL",
    commit: bool = True,
    received_at: datetime | None = None,  # historical imports/demo data only
) -> tuple[Purchase, list[dict[str, Any]]]:
    """Receive stock from a supplier. Returns (purchase, price_changes)."""
    sup = _supplier(db, data.supplier_id)

    po = None
    if data.purchase_order_id is not None:
        po = db.scalar(
            select(PurchaseOrder)
            .where(PurchaseOrder.id == data.purchase_order_id)
            .with_for_update(of=PurchaseOrder)
        )
        if po is None:
            raise ValidationFailed("Purchase order not found")
        if po.supplier_id != sup.id:
            raise ValidationFailed(f"{po.po_number} is for a different supplier")
        if po.status in ("RECEIVED", "CANCELLED"):
            raise ValidationFailed(f"{po.po_number} is already {po.status.lower()}")

    if data.supplier_invoice_number:
        dup = db.scalar(
            select(Purchase).where(
                Purchase.supplier_id == sup.id,
                func.upper(Purchase.supplier_invoice_number) == data.supplier_invoice_number,
            )
        )
        if dup:
            raise ConflictError(
                f"Invoice {data.supplier_invoice_number} from {sup.name} was already received "
                f"on {dup.received_at:%d %b %Y} ({dup.grn_number}).",
                code="DUPLICATE_INVOICE",
                details={"purchase_id": dup.id, "grn_number": dup.grn_number},
            )

    ids = sorted({line.product_id for line in data.items})
    products = _products(db, ids)
    if len(ids) != len(data.items):
        raise ValidationFailed("Each product can appear only once per delivery")
    po_items = {i.product_id: i for i in po.items} if po else {}

    purchase = Purchase(
        grn_number=numbering.next_number(db, "goods_received"),
        supplier_id=sup.id,
        purchase_order_id=po.id if po else None,
        supplier_invoice_number=data.supplier_invoice_number,
        invoice_date=data.invoice_date,
        subtotal=ZERO,
        tax_total=ZERO,
        grand_total=ZERO,
        source=source,
        notes=(data.notes or "").strip() or None,
        received_by_id=user.id,
    )
    if received_at is not None:
        purchase.received_at = received_at
    db.add(purchase)
    db.flush()

    subtotal = tax_total = ZERO
    for line in sorted(data.items, key=lambda li: li.product_id):  # consistent lock order
        product = products[line.product_id]
        inventory_service.validate_quantity(product, line.quantity)
        unit_cost = Decimal(line.unit_cost).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        rate = line.vat_rate if line.vat_rate is not None else product.vat_rate
        net = money(line.quantity * unit_cost)
        tax = vat_on_top(net, rate)
        previous = (
            product.purchase_price.quantize(Decimal("0.0001"))
            if product.purchase_price > 0
            else None
        )

        inventory_service.apply_movement(
            db,
            product_id=product.id,
            quantity=line.quantity,
            movement_type="PURCHASE_IN",
            user=user,
            unit_cost=unit_cost,
            batch_info=inventory_service.BatchInfo(line.batch_number, line.expiry_date),
            reference_type="purchase",
            reference_id=purchase.id,
            occurred_at=received_at,
            reason=f"{purchase.grn_number} from {sup.name}"
            + (f", invoice {data.supplier_invoice_number}" if data.supplier_invoice_number else ""),
        )
        po_item = po_items.get(product.id)
        if po_item is not None:
            po_item.quantity_received += line.quantity
        purchase.items.append(
            PurchaseItem(
                product_id=product.id,
                purchase_order_item_id=po_item.id if po_item else None,
                quantity=line.quantity,
                unit_cost=unit_cost,
                vat_rate=rate,
                tax_amount=tax,
                line_total=net + tax,
                previous_unit_cost=previous,
                batch_number=(line.batch_number or "").strip() or None,
                expiry_date=line.expiry_date,
            )
        )
        link = db.get(SupplierProduct, (sup.id, product.id))
        if link is None:
            link = SupplierProduct(supplier_id=sup.id, product_id=product.id)
            db.add(link)
        link.last_unit_price = money(unit_cost)
        subtotal += net
        tax_total += tax

    purchase.subtotal = subtotal
    purchase.tax_total = tax_total
    purchase.grand_total = subtotal + tax_total

    db.flush()
    changes = price_changes(purchase)
    if po is not None:
        done = all(i.quantity_received >= i.quantity_ordered for i in po.items)
        po.status = "RECEIVED" if done else "PARTIAL"

    audit_service.record(
        db,
        action="purchase.received",
        actor=user,
        ctx=ctx,
        entity_type="purchase",
        entity_id=purchase.id,
        after={
            "supplier": sup.name,
            "invoice": data.supplier_invoice_number,
            "total_kes": purchase.grand_total,
            "lines": len(data.items),
            "source": source,
            "price_changes": len(changes),
        },
    )
    if commit:
        db.commit()
        db.refresh(purchase)
    return purchase, changes


def get_purchase(db: Session, purchase_id: int) -> Purchase:
    p = db.get(Purchase, purchase_id)
    if p is None:
        raise NotFoundError("Goods received note not found")
    return p


def list_purchases(
    db: Session,
    params: PageParams,
    *,
    supplier_id: int | None,
    search: str | None,
) -> tuple[list[Purchase], int]:
    stmt = select(Purchase)
    if supplier_id:
        stmt = stmt.where(Purchase.supplier_id == supplier_id)
    if search:
        term = f"%{search.strip().upper()}%"
        stmt = stmt.where(
            func.upper(Purchase.grn_number).like(term)
            | func.upper(func.coalesce(Purchase.supplier_invoice_number, "")).like(term)
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Purchase.received_at.desc(), Purchase.id.desc())
        .offset(params.offset)
        .limit(params.page_size)
    ).all()
    return list(rows), total

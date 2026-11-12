"""Products: CRUD, search, barcode lookup, images and output shaping."""

import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailed
from app.models import Category, Product, ProductBatch, StockMovement, Supplier, User
from app.models.catalog import COUNT_UNITS
from app.schemas.catalog import ProductCreate, ProductOut, ProductUpdate, ProductWithCost
from app.schemas.common import PageParams
from app.services import audit_service, inventory_service
from app.services.audit_service import RequestContext
from app.utils import barcodes, images

TWO = Decimal("0.01")
StockFilter = Literal["out", "low", "ok", "over", "expiring"]


# --- Output shaping ----------------------------------------------------------------


def stock_status(p: Product) -> str:
    if p.quantity_on_hand <= 0:
        return "out"
    if p.min_stock_level > 0 and p.quantity_on_hand <= p.min_stock_level:
        return "low"
    if p.max_stock_level is not None and p.quantity_on_hand > p.max_stock_level:
        return "over"
    return "ok"


def margin_percent(p: Product) -> Decimal | None:
    """Gross margin on the VAT-exclusive selling price, at weighted average cost."""
    if p.avg_cost <= 0 or p.selling_price <= 0:
        return None
    net_price = p.selling_price * Decimal(100) / (Decimal(100) + p.vat_rate)
    return ((net_price - p.avg_cost) / net_price * 100).quantize(TWO, rounding=ROUND_HALF_UP)


def image_url(p: Product) -> str | None:
    if not p.image_path:
        return None
    return f"/api/v1/media/{p.image_path}"


def thumbnail_url(p: Product) -> str | None:
    if not p.image_path:
        return None
    folder, _, name = p.image_path.rpartition("/")
    return f"/api/v1/media/{folder}/thumbs/{name}"


def to_out(
    p: Product, *, with_cost: bool, next_expiry: date | None = None
) -> ProductOut | ProductWithCost:
    base: dict[str, Any] = {
        "id": p.id,
        "sku": p.sku,
        "barcode": p.barcode,
        "name": p.name,
        "description": p.description,
        "category": p.category,
        "default_supplier": p.default_supplier,
        "unit_of_measure": p.unit_of_measure,
        "image_url": image_url(p),
        "thumbnail_url": thumbnail_url(p),
        "selling_price": p.selling_price,
        "vat_rate": p.vat_rate,
        "quantity_on_hand": p.quantity_on_hand,
        "min_stock_level": p.min_stock_level,
        "max_stock_level": p.max_stock_level,
        "reorder_lead_time_days": p.reorder_lead_time_days,
        "tracks_expiry": p.tracks_expiry,
        "is_active": p.is_active,
        "stock_status": stock_status(p),
        "next_expiry": next_expiry,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }
    if not with_cost:
        return ProductOut.model_validate(base)
    value = (max(p.quantity_on_hand, Decimal(0)) * p.avg_cost).quantize(TWO, ROUND_HALF_UP)
    return ProductWithCost.model_validate(
        {
            **base,
            "purchase_price": p.purchase_price,
            "avg_cost": p.avg_cost,
            "stock_value": value,
            "margin_percent": margin_percent(p),
        }
    )


def next_expiries(db: Session, product_ids: list[int]) -> dict[int, date]:
    if not product_ids:
        return {}
    return dict(
        db.execute(
            select(ProductBatch.product_id, func.min(ProductBatch.expiry_date))
            .where(
                ProductBatch.product_id.in_(product_ids),
                ProductBatch.quantity_remaining > 0,
                ProductBatch.expiry_date.is_not(None),
            )
            .group_by(ProductBatch.product_id)
        ).all()
    )


def snapshot(p: Product) -> dict[str, Any]:
    return {
        "sku": p.sku,
        "barcode": p.barcode,
        "name": p.name,
        "category_id": p.category_id,
        "default_supplier_id": p.default_supplier_id,
        "unit_of_measure": p.unit_of_measure,
        "selling_price": p.selling_price,
        "purchase_price": p.purchase_price,
        "vat_rate": p.vat_rate,
        "min_stock_level": p.min_stock_level,
        "max_stock_level": p.max_stock_level,
        "tracks_expiry": p.tracks_expiry,
        "is_active": p.is_active,
    }


# --- Queries ---------------------------------------------------------------------


def get_product(db: Session, product_id: int) -> Product:
    p = db.get(Product, product_id)
    if p is None:
        raise NotFoundError("Product not found")
    return p


def _category_and_children(db: Session, category_id: int) -> list[int]:
    ids, frontier = {category_id}, [category_id]
    while frontier:
        children = db.scalars(select(Category.id).where(Category.parent_id.in_(frontier))).all()
        frontier = [c for c in children if c not in ids]
        ids.update(frontier)
    return list(ids)


def list_products(
    db: Session,
    params: PageParams,
    *,
    search: str | None = None,
    category_id: int | None = None,
    supplier_id: int | None = None,
    stock: StockFilter | None = None,
    is_active: bool | None = True,
    sort: str = "name",
) -> tuple[list[Product], int]:
    stmt = select(Product)
    if search:
        term = search.strip()
        like = f"%{term.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Product.name).like(like),
                func.upper(Product.sku) == term.upper(),
                Product.barcode == term,
                func.lower(Product.sku).like(like),
                func.word_similarity(term, Product.name) >= 0.45,  # pg_trgm: tolerates typos
            )
        )
    if category_id:
        stmt = stmt.where(Product.category_id.in_(_category_and_children(db, category_id)))
    if supplier_id:
        stmt = stmt.where(Product.default_supplier_id == supplier_id)
    if is_active is not None:
        stmt = stmt.where(Product.is_active.is_(is_active))
    if stock == "out":
        stmt = stmt.where(Product.quantity_on_hand <= 0)
    elif stock == "low":
        stmt = stmt.where(
            Product.quantity_on_hand > 0,
            Product.min_stock_level > 0,
            Product.quantity_on_hand <= Product.min_stock_level,
        )
    elif stock == "over":
        stmt = stmt.where(
            Product.max_stock_level.is_not(None),
            Product.quantity_on_hand > Product.max_stock_level,
        )
    elif stock == "ok":
        stmt = stmt.where(
            Product.quantity_on_hand > 0,
            or_(Product.min_stock_level == 0, Product.quantity_on_hand > Product.min_stock_level),
        )
    elif stock == "expiring":
        horizon = date.today() + timedelta(days=get_settings().expiry_warning_days)
        stmt = stmt.where(
            select(ProductBatch.id)
            .where(
                ProductBatch.product_id == Product.id,
                ProductBatch.quantity_remaining > 0,
                ProductBatch.expiry_date <= horizon,
            )
            .exists()
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order = {
        "name": [func.lower(Product.name)],
        "-updated": [Product.updated_at.desc()],
        "quantity": [Product.quantity_on_hand, func.lower(Product.name)],
        "sku": [func.upper(Product.sku)],
    }.get(sort, [func.lower(Product.name)])
    if search:
        order = [func.word_similarity(search.strip(), Product.name).desc(), *order]
    rows = db.scalars(
        stmt.order_by(*order, Product.id).offset(params.offset).limit(params.page_size)
    ).all()
    return list(rows), total


def lookup(db: Session, code: str) -> tuple[Product, str]:
    """Exact match for a scanned barcode or typed SKU (active products only)."""
    code = code.strip()
    if not code:
        raise ValidationFailed("Enter or scan a code")
    p = db.scalar(select(Product).where(Product.barcode == code.upper(), Product.is_active))
    if p:
        return p, "barcode"
    p = db.scalar(select(Product).where(func.upper(Product.sku) == code.upper(), Product.is_active))
    if p:
        return p, "sku"
    raise NotFoundError(f"No active product has the code {code}")


# --- Writes ------------------------------------------------------------------------


def _check_refs(db: Session, category_id: int | None, supplier_id: int | None) -> None:
    if category_id is not None:
        cat = db.get(Category, category_id)
        if cat is None or not cat.is_active:
            raise ValidationFailed(
                "Choose an active category",
                details=[{"field": "category_id", "message": "not found or inactive"}],
            )
    if supplier_id is not None:
        sup = db.get(Supplier, supplier_id)
        if sup is None or not sup.is_active:
            raise ValidationFailed(
                "Choose an active supplier",
                details=[{"field": "default_supplier_id", "message": "not found or inactive"}],
            )


def _check_unique(
    db: Session, *, sku: str | None, barcode: str | None, exclude: int | None = None
) -> None:
    if sku:
        stmt = select(Product.id).where(func.upper(Product.sku) == sku.upper())
        if exclude:
            stmt = stmt.where(Product.id != exclude)
        if db.scalar(stmt):
            raise ConflictError(
                "Another product already uses that SKU",
                details=[{"field": "sku", "message": "already in use"}],
            )
    if barcode:
        stmt = select(Product).where(Product.barcode == barcode)
        if exclude:
            stmt = stmt.where(Product.id != exclude)
        other = db.scalar(stmt)
        if other:
            raise ConflictError(
                f"That barcode already belongs to {other.name}",
                details=[{"field": "barcode", "message": f"used by {other.name}"}],
            )


def create_product(db: Session, data: ProductCreate, actor: User, ctx: RequestContext) -> Product:
    _check_refs(db, data.category_id, data.default_supplier_id)
    _check_unique(db, sku=data.sku, barcode=data.barcode)

    values = data.model_dump(exclude={"opening_stock", "sku"})
    product = Product(**values, sku=data.sku or f"TMP-{uuid.uuid4().hex[:12]}")
    db.add(product)
    db.flush()
    if not data.sku:
        product.sku = f"SKU-{product.id:06d}"

    audit_service.record(
        db,
        action="product.create",
        actor=actor,
        ctx=ctx,
        entity_type="product",
        entity_id=product.id,
        after=snapshot(product),
    )
    if data.opening_stock:
        o = data.opening_stock
        inventory_service.apply_movement(
            db,
            product_id=product.id,
            quantity=o.quantity,
            movement_type="OPENING",
            user=actor,
            unit_cost=o.unit_cost,
            batch_info=inventory_service.BatchInfo(o.batch_number, o.expiry_date),
            reference_type="product",
            reference_id=product.id,
            reason="Opening stock",
        )
    db.commit()
    db.refresh(product)
    return product


def update_product(
    db: Session, p: Product, data: ProductUpdate, actor: User, ctx: RequestContext
) -> Product:
    before = snapshot(p)
    changes = data.model_dump(exclude_unset=True)
    _check_refs(db, changes.get("category_id"), changes.get("default_supplier_id"))
    for required in (
        "name",
        "sku",
        "unit_of_measure",
        "selling_price",
        "purchase_price",
        "vat_rate",
        "min_stock_level",
        "reorder_lead_time_days",
        "tracks_expiry",
        "is_active",
    ):
        if required in changes and changes[required] is None:
            del changes[required]
    _check_unique(db, sku=changes.get("sku"), barcode=changes.get("barcode"), exclude=p.id)

    new_unit = changes.get("unit_of_measure")
    if new_unit in COUNT_UNITS and p.quantity_on_hand != p.quantity_on_hand.to_integral_value():
        raise ValidationFailed(
            f"{p.name} has {inventory_service.fmt(p.quantity_on_hand)} in stock, which is not a "
            f"whole number of {new_unit}. Adjust the stock first."
        )
    new_min = changes.get("min_stock_level", p.min_stock_level)
    new_max = changes.get("max_stock_level", p.max_stock_level)
    if new_max is not None and new_max < new_min:
        raise ValidationFailed("Maximum stock level cannot be below the minimum")

    for key, value in changes.items():
        setattr(p, key, value)
    db.flush()
    old, new = audit_service.diff(before, snapshot(p))
    if new:
        action = "product.update"
        if set(new) == {"is_active"}:
            action = "product.activate" if p.is_active else "product.deactivate"
        audit_service.record(
            db,
            action=action,
            actor=actor,
            ctx=ctx,
            entity_type="product",
            entity_id=p.id,
            before=old,
            after=new,
        )
    db.commit()
    db.refresh(p)
    return p


def delete_product(db: Session, p: Product, actor: User, ctx: RequestContext) -> None:
    """Hard delete is only allowed for products that never had any stock activity."""
    if db.scalar(select(StockMovement.id).where(StockMovement.product_id == p.id).limit(1)):
        raise ConflictError(
            f"{p.name} has stock history, so it cannot be deleted. Deactivate it instead; "
            "it will disappear from lists and the till but its history is kept.",
            code="HAS_HISTORY",
        )
    settings = get_settings()
    audit_service.record(
        db,
        action="product.delete",
        actor=actor,
        ctx=ctx,
        entity_type="product",
        entity_id=p.id,
        before=snapshot(p),
    )
    image = p.image_path
    db.execute(delete(ProductBatch).where(ProductBatch.product_id == p.id))
    db.delete(p)
    db.commit()
    images.delete_stored(settings.storage_dir, image)


def assign_internal_barcode(db: Session, p: Product, actor: User, ctx: RequestContext) -> Product:
    if p.barcode:
        raise ConflictError("This product already has a barcode")
    code = barcodes.internal_ean13(p.id)
    _check_unique(db, sku=None, barcode=code, exclude=p.id)
    p.barcode = code
    audit_service.record(
        db,
        action="product.barcode_generated",
        actor=actor,
        ctx=ctx,
        entity_type="product",
        entity_id=p.id,
        after={"barcode": code},
    )
    db.commit()
    db.refresh(p)
    return p


def set_image(db: Session, p: Product, data: bytes, actor: User, ctx: RequestContext) -> Product:
    settings = get_settings()
    try:
        processed = images.process_product_image(data, max_bytes=settings.max_image_mb * 1024**2)
    except images.ImageRejected as exc:
        raise ValidationFailed(str(exc), code="INVALID_IMAGE") from exc
    old = p.image_path
    p.image_path = images.save_product_image(settings.storage_dir, processed)
    audit_service.record(
        db,
        action="product.image_updated",
        actor=actor,
        ctx=ctx,
        entity_type="product",
        entity_id=p.id,
    )
    db.commit()
    images.delete_stored(settings.storage_dir, old)
    db.refresh(p)
    return p


def remove_image(db: Session, p: Product, actor: User, ctx: RequestContext) -> Product:
    old = p.image_path
    p.image_path = None
    audit_service.record(
        db,
        action="product.image_removed",
        actor=actor,
        ctx=ctx,
        entity_type="product",
        entity_id=p.id,
    )
    db.commit()
    images.delete_stored(get_settings().storage_dir, old)
    db.refresh(p)
    return p


def batches(db: Session, product_id: int, *, include_empty: bool = False) -> list[ProductBatch]:
    stmt = select(ProductBatch).where(ProductBatch.product_id == product_id)
    if not include_empty:
        stmt = stmt.where(ProductBatch.quantity_remaining > 0)
    return list(
        db.scalars(
            stmt.order_by(ProductBatch.expiry_date.asc().nulls_last(), ProductBatch.received_at)
        )
    )

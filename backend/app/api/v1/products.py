"""Products: catalogue, search, barcode lookup, barcode labels and images."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status

from app.api.deps import Ctx, DbSession, Pagination, require
from app.api.v1.suppliers import link_out
from app.core.config import get_settings
from app.core.exceptions import PermissionDenied, ValidationFailed
from app.core.permissions import P
from app.models import Product, User
from app.schemas.catalog import (
    BatchOut,
    ProductCreate,
    ProductLookup,
    ProductOut,
    ProductUpdate,
    ProductWithCost,
)
from app.schemas.common import Message, Page
from app.schemas.suppliers import SupplierProductOut
from app.services import catalog_service, product_service
from app.utils.barcodes import render_svg

router = APIRouter(prefix="/products", tags=["Products"])

Reader = Annotated[User, Depends(require(P.PRODUCTS_READ))]
Writer = Annotated[User, Depends(require(P.PRODUCTS_WRITE))]
Deleter = Annotated[User, Depends(require(P.PRODUCTS_DELETE))]
StockReader = Annotated[User, Depends(require(P.STOCK_READ))]

ProductResponse = ProductWithCost | ProductOut


def can_see_cost(user: User) -> bool:
    return P.PRODUCTS_VIEW_COST.value in user.permission_codes


def out(db, p: Product, user: User) -> ProductResponse:  # type: ignore[no-untyped-def]
    expiry = product_service.next_expiries(db, [p.id]).get(p.id)
    return product_service.to_out(p, with_cost=can_see_cost(user), next_expiry=expiry)


@router.get("", response_model=Page[ProductWithCost] | Page[ProductOut])
def list_products(
    user: Reader,
    db: DbSession,
    pagination: Pagination,
    search: Annotated[str | None, Query(max_length=100)] = None,
    category_id: int | None = None,
    supplier_id: int | None = None,
    stock: Literal["out", "low", "ok", "over", "expiring"] | None = None,
    status_filter: Annotated[
        Literal["active", "inactive", "all"], Query(alias="status")
    ] = "active",
    sort: Literal["name", "-updated", "quantity", "sku"] = "name",
):  # type: ignore[no-untyped-def]
    """Search by name (typo-tolerant), SKU or barcode; filter by category and stock state."""
    is_active = {"active": True, "inactive": False, "all": None}[status_filter]
    rows, total = product_service.list_products(
        db,
        pagination,
        search=search,
        category_id=category_id,
        supplier_id=supplier_id,
        stock=stock,
        is_active=is_active,
        sort=sort,
    )
    expiries = product_service.next_expiries(db, [p.id for p in rows])
    with_cost = can_see_cost(user)
    items = [
        product_service.to_out(p, with_cost=with_cost, next_expiry=expiries.get(p.id)) for p in rows
    ]
    return Page.build(items, total, pagination)


@router.get("/lookup", response_model=ProductLookup)
def lookup(
    user: Reader, db: DbSession, code: Annotated[str, Query(min_length=1, max_length=40)]
) -> ProductLookup:
    """Find the product for a scanned barcode or typed SKU (exact match)."""
    p, match = product_service.lookup(db, code)
    return ProductLookup(match=match, product=out(db, p, user))  # type: ignore[arg-type]


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(body: ProductCreate, actor: Writer, db: DbSession, ctx: Ctx):  # type: ignore[no-untyped-def]
    if (body.purchase_price or body.opening_stock) and not can_see_cost(actor):
        raise PermissionDenied("You cannot set purchase costs.")
    p = product_service.create_product(db, body, actor, ctx)
    return out(db, p, actor)


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: int, user: Reader, db: DbSession):  # type: ignore[no-untyped-def]
    return out(db, product_service.get_product(db, product_id), user)


@router.patch("/{product_id}", response_model=ProductResponse)
def update_product(product_id: int, body: ProductUpdate, actor: Writer, db: DbSession, ctx: Ctx):  # type: ignore[no-untyped-def]
    sent = body.model_fields_set
    if "is_active" in sent and P.PRODUCTS_DELETE.value not in actor.permission_codes:
        raise PermissionDenied("Only a Store Manager or Administrator can deactivate products.")
    if "purchase_price" in sent and not can_see_cost(actor):
        raise PermissionDenied("You cannot change purchase costs.")
    p = product_service.get_product(db, product_id)
    return out(db, product_service.update_product(db, p, body, actor, ctx), actor)


@router.delete("/{product_id}", response_model=Message)
def delete_product(product_id: int, actor: Deleter, db: DbSession, ctx: Ctx) -> Message:
    """Permanently delete a product that has never had stock. Otherwise deactivate it."""
    p = product_service.get_product(db, product_id)
    product_service.delete_product(db, p, actor, ctx)
    return Message(message="Product deleted")


@router.post("/{product_id}/barcode", response_model=ProductResponse)
def generate_barcode(product_id: int, actor: Writer, db: DbSession, ctx: Ctx):  # type: ignore[no-untyped-def]
    """Give a product without a manufacturer barcode an internal EAN-13 (prefix 20)."""
    p = product_service.get_product(db, product_id)
    return out(db, product_service.assign_internal_barcode(db, p, actor, ctx), actor)


@router.get("/{product_id}/barcode.svg", response_class=Response)
def barcode_svg(product_id: int, _: Reader, db: DbSession) -> Response:
    p = product_service.get_product(db, product_id)
    if not p.barcode:
        raise ValidationFailed("This product has no barcode yet", code="NO_BARCODE")
    return Response(
        content=render_svg(p.barcode),
        media_type="image/svg+xml",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.post("/{product_id}/image", response_model=ProductResponse)
async def upload_image(
    product_id: int,
    actor: Writer,
    db: DbSession,
    ctx: Ctx,
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP, max 5 MB")],
):  # type: ignore[no-untyped-def]
    limit = get_settings().max_image_mb * 1024 * 1024
    data = await file.read(limit + 1)  # never read more than the limit into memory
    p = product_service.get_product(db, product_id)
    return out(db, product_service.set_image(db, p, data, actor, ctx), actor)


@router.delete("/{product_id}/image", response_model=ProductResponse)
def delete_image(product_id: int, actor: Writer, db: DbSession, ctx: Ctx):  # type: ignore[no-untyped-def]
    p = product_service.get_product(db, product_id)
    return out(db, product_service.remove_image(db, p, actor, ctx), actor)


@router.get("/{product_id}/batches", response_model=list[BatchOut])
def product_batches(
    product_id: int, user: StockReader, db: DbSession, include_empty: bool = False
) -> list[BatchOut]:
    from datetime import date

    product_service.get_product(db, product_id)
    today = date.today()
    result = []
    for b in product_service.batches(db, product_id, include_empty=include_empty):
        item = BatchOut.model_validate(b)
        item.days_to_expiry = (b.expiry_date - today).days if b.expiry_date else None
        if not can_see_cost(user):
            item.unit_cost = None
        result.append(item)
    return result


@router.get("/{product_id}/suppliers", response_model=list[SupplierProductOut])
def product_suppliers(
    product_id: int,
    user: Annotated[User, Depends(require(P.SUPPLIERS_READ))],
    db: DbSession,
) -> list[SupplierProductOut]:
    """Suppliers of this product with their last prices (cheapest first)."""
    product_service.get_product(db, product_id)
    links = catalog_service.list_supplier_products(db, product_id=product_id)
    links.sort(key=lambda link: (link.last_unit_price is None, link.last_unit_price or 0))
    return [link_out(link, with_cost=can_see_cost(user)) for link in links]

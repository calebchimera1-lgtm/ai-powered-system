"""Suppliers and the products they supply."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Ctx, DbSession, Pagination, require
from app.core.permissions import P
from app.models import Supplier, SupplierProduct, User
from app.schemas.common import Message, Page
from app.schemas.suppliers import (
    SupplierIn,
    SupplierOut,
    SupplierProductIn,
    SupplierProductOut,
    SupplierUpdate,
)
from app.services import catalog_service

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])

Reader = Annotated[User, Depends(require(P.SUPPLIERS_READ))]
Writer = Annotated[User, Depends(require(P.SUPPLIERS_WRITE))]


def _out(s: Supplier, count: int = 0) -> SupplierOut:
    out = SupplierOut.model_validate(s)
    out.product_count = count
    return out


def link_out(link: SupplierProduct, *, with_cost: bool) -> SupplierProductOut:
    return SupplierProductOut(
        supplier_id=link.supplier_id,
        supplier_name=link.supplier.name,
        product_id=link.product_id,
        product_name=link.product.name,
        product_sku=link.product.sku,
        supplier_sku=link.supplier_sku,
        last_unit_price=link.last_unit_price if with_cost else None,
        lead_time_days=link.lead_time_days,
        updated_at=link.updated_at,
    )


@router.get("", response_model=Page[SupplierOut])
def list_suppliers(
    _: Reader,
    db: DbSession,
    pagination: Pagination,
    search: Annotated[str | None, Query(max_length=100)] = None,
    is_active: bool | None = None,
) -> Page[SupplierOut]:
    rows, total = catalog_service.list_suppliers(db, pagination, search=search, is_active=is_active)
    counts = catalog_service.supplier_product_counts(db, [s.id for s in rows])
    return Page.build([_out(s, counts.get(s.id, 0)) for s in rows], total, pagination)


@router.post("", response_model=SupplierOut, status_code=status.HTTP_201_CREATED)
def create_supplier(body: SupplierIn, actor: Writer, db: DbSession, ctx: Ctx) -> SupplierOut:
    return _out(catalog_service.create_supplier(db, body, actor, ctx))


@router.get("/{supplier_id}", response_model=SupplierOut)
def get_supplier(supplier_id: int, _: Reader, db: DbSession) -> SupplierOut:
    s = catalog_service.get_supplier(db, supplier_id)
    return _out(s, catalog_service.supplier_product_counts(db, [s.id]).get(s.id, 0))


@router.patch("/{supplier_id}", response_model=SupplierOut)
def update_supplier(
    supplier_id: int, body: SupplierUpdate, actor: Writer, db: DbSession, ctx: Ctx
) -> SupplierOut:
    s = catalog_service.get_supplier(db, supplier_id)
    s = catalog_service.update_supplier(db, s, body, actor, ctx)
    return _out(s, catalog_service.supplier_product_counts(db, [s.id]).get(s.id, 0))


@router.get("/{supplier_id}/products", response_model=list[SupplierProductOut])
def supplier_products(supplier_id: int, user: Reader, db: DbSession) -> list[SupplierProductOut]:
    catalog_service.get_supplier(db, supplier_id)
    with_cost = P.PRODUCTS_VIEW_COST.value in user.permission_codes
    return [
        link_out(link, with_cost=with_cost)
        for link in catalog_service.list_supplier_products(db, supplier_id=supplier_id)
    ]


@router.put("/{supplier_id}/products/{product_id}", response_model=SupplierProductOut)
def link_product(
    supplier_id: int,
    product_id: int,
    body: SupplierProductIn,
    actor: Writer,
    db: DbSession,
    ctx: Ctx,
) -> SupplierProductOut:
    """Record that this supplier sells the product (and their code / last price)."""
    s = catalog_service.get_supplier(db, supplier_id)
    link = catalog_service.upsert_supplier_product(db, s, product_id, body, actor, ctx)
    return link_out(link, with_cost=P.PRODUCTS_VIEW_COST.value in actor.permission_codes)


@router.delete("/{supplier_id}/products/{product_id}", response_model=Message)
def unlink_product(
    supplier_id: int, product_id: int, actor: Writer, db: DbSession, ctx: Ctx
) -> Message:
    s = catalog_service.get_supplier(db, supplier_id)
    catalog_service.remove_supplier_product(db, s, product_id, actor, ctx)
    return Message(message="Product removed from supplier")

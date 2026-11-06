"""Categories and suppliers: CRUD with integrity rules."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationFailed
from app.models import Category, Product, Supplier, SupplierProduct, User
from app.schemas.catalog import CategoryIn, CategoryUpdate
from app.schemas.common import PageParams
from app.schemas.suppliers import SupplierIn, SupplierProductIn, SupplierUpdate
from app.services import audit_service
from app.services.audit_service import RequestContext

# --- Categories ---------------------------------------------------------------


def _cat_snapshot(c: Category) -> dict[str, Any]:
    return {
        "name": c.name,
        "description": c.description,
        "parent_id": c.parent_id,
        "is_active": c.is_active,
    }


def get_category(db: Session, category_id: int) -> Category:
    cat = db.get(Category, category_id)
    if cat is None:
        raise NotFoundError("Category not found")
    return cat


def list_categories(db: Session, *, include_inactive: bool = True) -> list[dict[str, Any]]:
    """All categories with product counts and a readable path ("Food › Dry goods")."""
    cats = list(db.scalars(select(Category).order_by(Category.name)))
    counts = dict(
        db.execute(
            select(Product.category_id, func.count(Product.id))
            .where(Product.is_active.is_(True))
            .group_by(Product.category_id)
        ).all()
    )
    by_id = {c.id: c for c in cats}

    def path(c: Category) -> str:
        parts, seen, node = [], set(), c
        while node is not None and node.id not in seen:
            seen.add(node.id)
            parts.append(node.name)
            node = by_id.get(node.parent_id) if node.parent_id else None
        return " › ".join(reversed(parts))

    rows = [
        {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "parent_id": c.parent_id,
            "is_active": c.is_active,
            "product_count": counts.get(c.id, 0),
            "path": path(c),
        }
        for c in cats
        if include_inactive or c.is_active
    ]
    return sorted(rows, key=lambda r: r["path"].lower())


def _check_parent(db: Session, parent_id: int | None, self_id: int | None = None) -> None:
    if parent_id is None:
        return
    parent = db.get(Category, parent_id)
    if parent is None:
        raise ValidationFailed(
            "Parent category not found", details=[{"field": "parent_id", "message": "not found"}]
        )
    # Walk up from the new parent; reaching ourselves would create a loop.
    node, depth = parent, 0
    while node is not None:
        if self_id is not None and node.id == self_id:
            raise ValidationFailed("A category cannot be placed inside itself")
        depth += 1
        node = db.get(Category, node.parent_id) if node.parent_id else None
    if depth >= 3:
        raise ValidationFailed("Categories can be nested at most three levels deep")


def _unique_cat_name(db: Session, name: str, parent_id: int | None, exclude: int | None) -> None:
    stmt = select(Category.id).where(
        func.lower(Category.name) == name.lower(),
        Category.parent_id.is_(None) if parent_id is None else Category.parent_id == parent_id,
    )
    if exclude:
        stmt = stmt.where(Category.id != exclude)
    if db.scalar(stmt):
        raise ConflictError(
            "A category with that name already exists here",
            details=[{"field": "name", "message": "already exists"}],
        )


def create_category(db: Session, data: CategoryIn, actor: User, ctx: RequestContext) -> Category:
    _check_parent(db, data.parent_id)
    _unique_cat_name(db, data.name, data.parent_id, None)
    cat = Category(name=data.name, description=data.description, parent_id=data.parent_id)
    db.add(cat)
    db.flush()
    audit_service.record(
        db,
        action="category.create",
        actor=actor,
        ctx=ctx,
        entity_type="category",
        entity_id=cat.id,
        after=_cat_snapshot(cat),
    )
    db.commit()
    return cat


def update_category(
    db: Session, cat: Category, data: CategoryUpdate, actor: User, ctx: RequestContext
) -> Category:
    before = _cat_snapshot(cat)
    changes = data.model_dump(exclude_unset=True)
    if "parent_id" in changes:
        _check_parent(db, changes["parent_id"], self_id=cat.id)
        cat.parent_id = changes["parent_id"]
    if changes.get("name"):
        name = " ".join(changes["name"].split())
        _unique_cat_name(db, name, cat.parent_id, cat.id)
        cat.name = name
    if "description" in changes:
        cat.description = changes["description"]
    if changes.get("is_active") is not None:
        cat.is_active = changes["is_active"]
    db.flush()
    old, new = audit_service.diff(before, _cat_snapshot(cat))
    if new:
        audit_service.record(
            db,
            action="category.update",
            actor=actor,
            ctx=ctx,
            entity_type="category",
            entity_id=cat.id,
            before=old,
            after=new,
        )
    db.commit()
    return cat


def delete_category(db: Session, cat: Category, actor: User, ctx: RequestContext) -> None:
    if db.scalar(select(Product.id).where(Product.category_id == cat.id).limit(1)):
        raise ConflictError(
            "This category still has products. Move them to another category, "
            "or deactivate the category instead."
        )
    if db.scalar(select(Category.id).where(Category.parent_id == cat.id).limit(1)):
        raise ConflictError("This category has sub-categories. Remove or move them first.")
    audit_service.record(
        db,
        action="category.delete",
        actor=actor,
        ctx=ctx,
        entity_type="category",
        entity_id=cat.id,
        before=_cat_snapshot(cat),
    )
    db.delete(cat)
    db.commit()


# --- Suppliers ------------------------------------------------------------------


def _sup_snapshot(s: Supplier) -> dict[str, Any]:
    return {
        "name": s.name,
        "kra_pin": s.kra_pin,
        "contact_person": s.contact_person,
        "phone": s.phone,
        "email": s.email,
        "address": s.address,
        "payment_terms_days": s.payment_terms_days,
        "is_active": s.is_active,
    }


def get_supplier(db: Session, supplier_id: int) -> Supplier:
    sup = db.get(Supplier, supplier_id)
    if sup is None:
        raise NotFoundError("Supplier not found")
    return sup


def supplier_product_counts(db: Session, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    return dict(
        db.execute(
            select(SupplierProduct.supplier_id, func.count())
            .where(SupplierProduct.supplier_id.in_(ids))
            .group_by(SupplierProduct.supplier_id)
        ).all()
    )


def list_suppliers(
    db: Session, params: PageParams, *, search: str | None, is_active: bool | None
) -> tuple[list[Supplier], int]:
    stmt = select(Supplier)
    if search:
        term = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            func.lower(Supplier.name).like(term)
            | func.lower(func.coalesce(Supplier.contact_person, "")).like(term)
            | func.lower(func.coalesce(Supplier.kra_pin, "")).like(term)
            | func.coalesce(Supplier.phone, "").like(term)
        )
    if is_active is not None:
        stmt = stmt.where(Supplier.is_active.is_(is_active))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(func.lower(Supplier.name)).offset(params.offset).limit(params.page_size)
    ).all()
    return list(rows), total


def _unique_supplier(
    db: Session, name: str | None, pin: str | None, exclude: int | None = None
) -> None:
    if name:
        stmt = select(Supplier.id).where(func.lower(Supplier.name) == name.lower())
        if exclude:
            stmt = stmt.where(Supplier.id != exclude)
        if db.scalar(stmt):
            raise ConflictError(
                "A supplier with that name already exists",
                details=[{"field": "name", "message": "already exists"}],
            )
    if pin:
        stmt = select(Supplier.id).where(Supplier.kra_pin == pin)
        if exclude:
            stmt = stmt.where(Supplier.id != exclude)
        if db.scalar(stmt):
            raise ConflictError(
                "Another supplier already has that KRA PIN",
                details=[{"field": "kra_pin", "message": "already registered"}],
            )


def create_supplier(db: Session, data: SupplierIn, actor: User, ctx: RequestContext) -> Supplier:
    _unique_supplier(db, data.name, data.kra_pin)
    values = data.model_dump()
    if values.get("email"):
        values["email"] = str(values["email"]).lower()
    sup = Supplier(**values)
    db.add(sup)
    db.flush()
    audit_service.record(
        db,
        action="supplier.create",
        actor=actor,
        ctx=ctx,
        entity_type="supplier",
        entity_id=sup.id,
        after=_sup_snapshot(sup),
    )
    db.commit()
    return sup


def update_supplier(
    db: Session, sup: Supplier, data: SupplierUpdate, actor: User, ctx: RequestContext
) -> Supplier:
    before = _sup_snapshot(sup)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("name"):
        changes["name"] = " ".join(changes["name"].split())
    _unique_supplier(db, changes.get("name"), changes.get("kra_pin"), exclude=sup.id)
    if changes.get("email"):
        changes["email"] = str(changes["email"]).lower()
    for key, value in changes.items():
        if key == "name" and not value:
            continue
        setattr(sup, key, value)
    db.flush()
    old, new = audit_service.diff(before, _sup_snapshot(sup))
    if new:
        audit_service.record(
            db,
            action="supplier.update",
            actor=actor,
            ctx=ctx,
            entity_type="supplier",
            entity_id=sup.id,
            before=old,
            after=new,
        )
    db.commit()
    return sup


def list_supplier_products(
    db: Session, *, supplier_id: int | None = None, product_id: int | None = None
) -> list[SupplierProduct]:
    stmt = select(SupplierProduct)
    if supplier_id is not None:
        stmt = stmt.where(SupplierProduct.supplier_id == supplier_id)
    if product_id is not None:
        stmt = stmt.where(SupplierProduct.product_id == product_id)
    rows = db.scalars(stmt).unique().all()
    return sorted(rows, key=lambda r: (r.supplier.name.lower(), r.product.name.lower()))


def upsert_supplier_product(
    db: Session,
    sup: Supplier,
    product_id: int,
    data: SupplierProductIn,
    actor: User,
    ctx: RequestContext,
) -> SupplierProduct:
    if db.get(Product, product_id) is None:
        raise NotFoundError("Product not found")
    link = db.get(SupplierProduct, (sup.id, product_id))
    before = None
    if link is None:
        link = SupplierProduct(supplier_id=sup.id, product_id=product_id)
        db.add(link)
    else:
        before = {
            "supplier_sku": link.supplier_sku,
            "last_unit_price": link.last_unit_price,
            "lead_time_days": link.lead_time_days,
        }
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(link, key, value)
    db.flush()
    audit_service.record(
        db,
        action="supplier.product_linked",
        actor=actor,
        ctx=ctx,
        entity_type="supplier",
        entity_id=sup.id,
        before=before,
        after={"product_id": product_id, **data.model_dump(exclude_unset=True)},
    )
    db.commit()
    db.refresh(link)
    return link


def remove_supplier_product(
    db: Session, sup: Supplier, product_id: int, actor: User, ctx: RequestContext
) -> None:
    link = db.get(SupplierProduct, (sup.id, product_id))
    if link is None:
        raise NotFoundError("This supplier is not linked to that product")
    db.delete(link)
    audit_service.record(
        db,
        action="supplier.product_unlinked",
        actor=actor,
        ctx=ctx,
        entity_type="supplier",
        entity_id=sup.id,
        details=f"product {product_id}",
    )
    db.commit()

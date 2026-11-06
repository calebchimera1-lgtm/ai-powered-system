"""Product categories."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import Ctx, DbSession, require
from app.core.permissions import P
from app.models import User
from app.schemas.catalog import CategoryIn, CategoryOut, CategoryUpdate
from app.schemas.common import Message
from app.services import catalog_service

router = APIRouter(prefix="/categories", tags=["Categories"])

Reader = Annotated[User, Depends(require(P.PRODUCTS_READ))]
Writer = Annotated[User, Depends(require(P.PRODUCTS_WRITE))]


def _one(db, category_id: int) -> CategoryOut:  # type: ignore[no-untyped-def]
    rows = {r["id"]: r for r in catalog_service.list_categories(db)}
    return CategoryOut.model_validate(rows[category_id])


@router.get("", response_model=list[CategoryOut])
def list_categories(_: Reader, db: DbSession, include_inactive: bool = False) -> list[CategoryOut]:
    rows = catalog_service.list_categories(db, include_inactive=include_inactive)
    return [CategoryOut.model_validate(r) for r in rows]


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(body: CategoryIn, actor: Writer, db: DbSession, ctx: Ctx) -> CategoryOut:
    cat = catalog_service.create_category(db, body, actor, ctx)
    return _one(db, cat.id)


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: int, body: CategoryUpdate, actor: Writer, db: DbSession, ctx: Ctx
) -> CategoryOut:
    cat = catalog_service.get_category(db, category_id)
    catalog_service.update_category(db, cat, body, actor, ctx)
    return _one(db, cat.id)


@router.delete("/{category_id}", response_model=Message)
def delete_category(category_id: int, actor: Writer, db: DbSession, ctx: Ctx) -> Message:
    cat = catalog_service.get_category(db, category_id)
    catalog_service.delete_category(db, cat, actor, ctx)
    return Message(message="Category deleted")

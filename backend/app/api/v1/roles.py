"""Read-only view of roles and their permissions."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.api.deps import DbSession, require
from app.core.permissions import P
from app.models import Role, User
from app.schemas.users import RoleOut

router = APIRouter(prefix="/roles", tags=["Roles"])


@router.get("", response_model=list[RoleOut])
def list_roles(
    _: Annotated[User, Depends(require(P.ROLES_READ, P.USERS_READ, any_of=True))],
    db: DbSession,
) -> list[RoleOut]:
    counts = dict(
        db.execute(
            select(User.role_id, func.count(User.id))
            .where(User.is_active.is_(True))
            .group_by(User.role_id)
        ).all()
    )
    order = ["super_admin", "store_manager", "inventory_officer", "cashier"]
    roles = sorted(
        db.scalars(select(Role)).all(),
        key=lambda r: order.index(r.name) if r.name in order else len(order),
    )
    out = []
    for role in roles:
        item = RoleOut.model_validate(role)
        item.user_count = counts.get(role.id, 0)
        out.append(item)
    return out

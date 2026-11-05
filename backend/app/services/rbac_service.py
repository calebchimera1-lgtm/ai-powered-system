"""Keeps the roles/permissions tables in step with the catalogue in core.permissions."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import (
    PERMISSION_DESCRIPTIONS,
    ROLE_DISPLAY,
    ROLE_PERMISSIONS,
    P,
    RoleName,
)
from app.models import Permission, Role

logger = logging.getLogger(__name__)


def sync_roles_and_permissions(db: Session) -> None:
    """Idempotently create/update permissions and the four built-in roles.

    Safe to run on every start-up. Permissions removed from the catalogue are deleted.
    """
    existing = {p.code: p for p in db.scalars(select(Permission))}
    for code in P:
        desc = PERMISSION_DESCRIPTIONS[code]
        perm = existing.get(code.value)
        if perm is None:
            perm = Permission(code=code.value, description=desc)
            db.add(perm)
            existing[code.value] = perm
        elif perm.description != desc:
            perm.description = desc
    for code, perm in list(existing.items()):
        if code not in {p.value for p in P}:
            db.delete(perm)
            del existing[code]
    db.flush()

    roles = {r.name: r for r in db.scalars(select(Role))}
    for role_name in RoleName:
        display, description = ROLE_DISPLAY[role_name]
        role = roles.get(role_name.value)
        if role is None:
            role = Role(name=role_name.value, display_name=display, description=description)
            db.add(role)
        role.display_name = display
        role.description = description
        wanted = sorted(ROLE_PERMISSIONS[role_name])
        role.permissions = [existing[p.value] for p in wanted]
    db.commit()
    logger.info("Roles and permissions synchronised (%d permissions)", len(existing))


def get_role(db: Session, name: str) -> Role | None:
    return db.scalar(select(Role).where(Role.name == name))

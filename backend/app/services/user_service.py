"""User administration: list, create, update, unlock and force sign-out."""

import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationFailed
from app.core.permissions import RoleName
from app.core.security import generate_token, hash_password
from app.models import AuditLog, Role, User
from app.schemas.common import PageParams
from app.schemas.users import UserCreate, UserUpdate
from app.services import audit_service, auth_service
from app.services.audit_service import RequestContext
from app.services.rbac_service import get_role


def snapshot(user: User) -> dict[str, Any]:
    """Audit-safe view of a user (never includes the password hash)."""
    return {
        "full_name": user.full_name,
        "username": user.username,
        "email": user.email,
        "phone": user.phone,
        "role": user.role.name if user.role else None,
        "is_active": user.is_active,
    }


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    return user


def list_users(
    db: Session,
    params: PageParams,
    *,
    search: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> tuple[list[User], int]:
    stmt = select(User).join(User.role)
    if search:
        term = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.full_name).like(term),
                func.lower(User.username).like(term),
                func.lower(User.email).like(term),
            )
        )
    if role:
        stmt = stmt.where(Role.name == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    users = db.scalars(
        stmt.order_by(User.full_name, User.id).offset(params.offset).limit(params.page_size)
    ).all()
    return list(users), total


def _require_role(db: Session, name: str) -> Role:
    role = get_role(db, name)
    if role is None:
        valid = ", ".join(r.value for r in RoleName)
        raise ValidationFailed(
            f"Unknown role '{name}'. Valid roles: {valid}",
            details=[{"field": "role", "message": "unknown role"}],
        )
    return role


def _ensure_unique(
    db: Session,
    *,
    username: str | None = None,
    email: str | None = None,
    exclude_id: int | None = None,
) -> None:
    if username:
        stmt = select(User.id).where(func.lower(User.username) == username.lower())
        if exclude_id:
            stmt = stmt.where(User.id != exclude_id)
        if db.scalar(stmt):
            raise ConflictError(
                "That username is already taken",
                details=[{"field": "username", "message": "already taken"}],
            )
    if email:
        stmt = select(User.id).where(func.lower(User.email) == email.lower())
        if exclude_id:
            stmt = stmt.where(User.id != exclude_id)
        if db.scalar(stmt):
            raise ConflictError(
                "That email address is already in use",
                details=[{"field": "email", "message": "already in use"}],
            )


def create_user(
    db: Session, data: UserCreate, actor: User, ctx: RequestContext
) -> tuple[User, str | None, datetime | None]:
    """Create a user. Returns (user, setup_token, setup_expiry).

    If no password is given, the account gets an unusable random password and a one-time
    setup token is issued so the new staff member chooses their own password.
    """
    role = _require_role(db, data.role)
    email = str(data.email).lower()
    _ensure_unique(db, username=data.username, email=email)

    if data.password:
        auth_service.validate_new_password(data.password, data.username)
        password_hash = hash_password(data.password)
    else:
        password_hash = hash_password(generate_token())

    user = User(
        full_name=data.full_name,
        username=data.username,
        email=email,
        phone=data.phone,
        role=role,
        password_hash=password_hash,
        is_active=True,
        must_change_password=True,  # admin-chosen passwords are temporary
        created_by_id=actor.id,
    )
    db.add(user)
    db.flush()
    audit_service.record(
        db,
        action="user.create",
        actor=actor,
        ctx=ctx,
        entity_type="user",
        entity_id=user.id,
        after=snapshot(user),
    )

    token = expires = None
    if not data.password:
        token, expires = auth_service.issue_reset_token(db, user, actor, ctx, note="account setup")
    db.commit()
    return user, token, expires


def _active_super_admins(db: Session) -> int:
    return (
        db.scalar(
            select(func.count(User.id))
            .join(User.role)
            .where(Role.name == RoleName.SUPER_ADMIN.value, User.is_active.is_(True))
        )
        or 0
    )


def update_user(
    db: Session, user: User, data: UserUpdate, actor: User, ctx: RequestContext
) -> User:
    before = snapshot(user)
    changes = data.model_dump(exclude_unset=True)
    is_self = user.id == actor.id

    if "role" in changes and changes["role"] is not None and changes["role"] != user.role.name:
        if is_self:
            raise ValidationFailed("You cannot change your own role.")
        new_role = _require_role(db, changes["role"])
        if (
            user.is_active
            and user.role.name == RoleName.SUPER_ADMIN.value
            and _active_super_admins(db) <= 1
        ):
            raise ValidationFailed("At least one active Super Administrator must remain.")
        user.role = new_role

    if "is_active" in changes and changes["is_active"] is not None:
        if changes["is_active"] is False and user.is_active:
            if is_self:
                raise ValidationFailed("You cannot deactivate your own account.")
            if user.role.name == RoleName.SUPER_ADMIN.value and _active_super_admins(db) <= 1:
                raise ValidationFailed("At least one active Super Administrator must remain.")
            auth_service.revoke_user_sessions(db, user.id, "deactivated")
        user.is_active = changes["is_active"]

    if changes.get("email"):
        email = str(changes["email"]).lower()
        _ensure_unique(db, email=email, exclude_id=user.id)
        user.email = email
    if changes.get("full_name"):
        user.full_name = " ".join(changes["full_name"].split())
    if "phone" in changes:
        user.phone = changes["phone"]

    db.flush()
    old, new = audit_service.diff(before, snapshot(user))
    if new:
        audit_service.record(
            db,
            action="user.update",
            actor=actor,
            ctx=ctx,
            entity_type="user",
            entity_id=user.id,
            before=old,
            after=new,
        )
    db.commit()
    db.refresh(user)
    return user


def unlock_user(db: Session, user: User, actor: User, ctx: RequestContext) -> User:
    user.locked_until = None
    user.failed_login_count = 0
    audit_service.record(
        db, action="user.unlock", actor=actor, ctx=ctx, entity_type="user", entity_id=user.id
    )
    db.commit()
    return user


def reset_mfa(db: Session, user: User, actor: User, ctx: RequestContext) -> User:
    """Turn off someone's two-step sign-in (e.g. lost phone) and sign them out everywhere."""
    if user.id == actor.id:
        raise ValidationFailed("Use My account to change your own two-step sign-in.")
    user.totp_secret = None
    user.totp_enabled_at = None
    user.totp_last_step = None
    auth_service.revoke_user_sessions(db, user.id, "mfa_reset_by_admin")
    audit_service.record(
        db, action="user.mfa_reset", actor=actor, ctx=ctx, entity_type="user", entity_id=user.id
    )
    db.commit()
    return user


def force_sign_out(db: Session, user: User, actor: User, ctx: RequestContext) -> int:
    count = auth_service.revoke_user_sessions(db, user.id, "revoked_by_admin")
    audit_service.record(
        db,
        action="user.sessions_revoked",
        actor=actor,
        ctx=ctx,
        entity_type="user",
        entity_id=user.id,
        details=f"{count} session(s) revoked",
    )
    db.commit()
    return count


def erase_personal_data(db: Session, user: User, actor: User, ctx: RequestContext) -> User:
    """Right to erasure (Kenya Data Protection Act 2019, s.40) for a former staff member.

    The account must already be deactivated. Name, username, e-mail, phone, password and
    two-step secret are replaced, and their sign-in sessions (with IP addresses and device
    names) are deleted. Sales, stock movements and audit entries they made are kept, as tax
    and accounting law requires, but now point to "Former staff member #<id>".
    """
    from app.models import PasswordResetToken, UserSession

    if user.id == actor.id:
        raise ValidationFailed("You cannot erase your own account.")
    if user.is_active:
        raise ValidationFailed("Deactivate the account first, then erase the personal data.")
    if user.username == f"erased-{user.id}":
        raise ValidationFailed("This person's personal data has already been erased.")
    user.full_name = f"Former staff member #{user.id}"
    user.username = f"erased-{user.id}"
    user.email = f"erased-{user.id}@example.com"  # reserved domain: never delivers
    user.phone = None
    user.password_hash = hash_password(secrets.token_urlsafe(48))
    user.totp_secret = user.totp_enabled_at = user.totp_last_step = None
    user.locked_until = None
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    # Earlier audit entries about this account held their name and contact details, and
    # entries they made held their IP address and device: keep the entries, drop those.
    personal = ("full_name", "username", "email", "phone")
    for entry in db.scalars(
        select(AuditLog).where(
            or_(
                (AuditLog.entity_type == "user") & (AuditLog.entity_id == str(user.id)),
                AuditLog.user_id == user.id,
            )
        )
    ):
        if entry.entity_type == "user" and entry.entity_id == str(user.id):
            for field in ("before", "after"):
                data = getattr(entry, field)
                if data and any(k in data for k in personal):
                    setattr(
                        entry,
                        field,
                        {k: ("[erased]" if k in personal else v) for k, v in data.items()},
                    )
        if entry.user_id == user.id:
            entry.ip_address = entry.user_agent = None
    audit_service.record(
        db,
        action="user.personal_data_erased",
        actor=actor,
        ctx=ctx,
        entity_type="user",
        entity_id=user.id,
        details="Name, username, e-mail, phone, password and sessions erased on request",
    )
    db.commit()
    db.refresh(user)
    return user

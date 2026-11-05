"""User administration endpoints (Super Administrator manages; Store Manager may view)."""

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Ctx, DbSession, Pagination, require
from app.core.config import get_settings
from app.core.permissions import P
from app.models import User
from app.schemas.common import Message, Page
from app.schemas.users import (
    PasswordResetIssued,
    UserCreate,
    UserCreated,
    UserOut,
    UserUpdate,
)
from app.services import auth_service, user_service

router = APIRouter(prefix="/users", tags=["Users"])

Reader = Annotated[User, Depends(require(P.USERS_READ))]
Manager = Annotated[User, Depends(require(P.USERS_MANAGE))]


def _out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.is_locked = bool(user.locked_until and user.locked_until > auth_service.utcnow())
    return out


def _reset_url(token: str) -> str:
    base = get_settings().frontend_url.rstrip("/")
    return f"{base}/reset-password?{urlencode({'token': token})}"


@router.get("", response_model=Page[UserOut])
def list_users(
    _: Reader,
    db: DbSession,
    pagination: Pagination,
    search: Annotated[str | None, Query(max_length=100)] = None,
    role: Annotated[str | None, Query(max_length=50)] = None,
    is_active: bool | None = None,
) -> Page[UserOut]:
    users, total = user_service.list_users(
        db, pagination, search=search, role=role, is_active=is_active
    )
    return Page.build([_out(u) for u in users], total, pagination)


@router.post("", response_model=UserCreated, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, actor: Manager, db: DbSession, ctx: Ctx) -> UserCreated:
    """Register a staff member. Omit `password` to get a one-time setup link instead."""
    user, token, expires = user_service.create_user(db, body, actor, ctx)
    return UserCreated(
        user=_out(user),
        setup_url=_reset_url(token) if token else None,
        setup_expires_at=expires,
    )


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, _: Reader, db: DbSession) -> UserOut:
    return _out(user_service.get_user(db, user_id))


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, actor: Manager, db: DbSession, ctx: Ctx) -> UserOut:
    user = user_service.get_user(db, user_id)
    return _out(user_service.update_user(db, user, body, actor, ctx))


@router.post("/{user_id}/reset-password", response_model=PasswordResetIssued)
def issue_password_reset(
    user_id: int, actor: Manager, db: DbSession, ctx: Ctx
) -> PasswordResetIssued:
    """Issue a one-time password reset link to give to the staff member."""
    user = user_service.get_user(db, user_id)
    token, expires = auth_service.issue_reset_token(db, user, actor, ctx, note="admin reset")
    db.commit()
    return PasswordResetIssued(reset_url=_reset_url(token), expires_at=expires)


@router.post("/{user_id}/unlock", response_model=UserOut)
def unlock_user(user_id: int, actor: Manager, db: DbSession, ctx: Ctx) -> UserOut:
    user = user_service.get_user(db, user_id)
    return _out(user_service.unlock_user(db, user, actor, ctx))


@router.post("/{user_id}/revoke-sessions", response_model=Message)
def revoke_sessions(user_id: int, actor: Manager, db: DbSession, ctx: Ctx) -> Message:
    """Sign the user out of every device."""
    user = user_service.get_user(db, user_id)
    count = user_service.force_sign_out(db, user, actor, ctx)
    return Message(message=f"{count} session(s) signed out")

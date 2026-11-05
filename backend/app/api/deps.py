"""Shared FastAPI dependencies: database session, current user and permission checks."""

from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import AuthenticationError, PermissionDenied
from app.core.permissions import P
from app.core.security import decode_access_token
from app.models import User, UserSession
from app.schemas.common import PageParams
from app.services.audit_service import RequestContext
from app.services.auth_service import utcnow

DbSession = Annotated[Session, Depends(get_db)]

_bearer = HTTPBearer(auto_error=False)


def get_current_session(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> UserSession:
    """Validate the bearer token AND its server-side session.

    Checking the session row means sign-out, deactivation and admin revocation take
    effect immediately instead of waiting for the access token to expire.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Not signed in")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token expired", code="TOKEN_EXPIRED") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid access token") from exc

    session = db.get(UserSession, int(payload["sid"]))
    if (
        session is None
        or str(session.user_id) != payload["sub"]
        or session.revoked_at is not None
        or session.expires_at <= utcnow()
    ):
        raise AuthenticationError("Session is no longer valid. Please sign in again.")
    if not session.user.is_active:
        raise AuthenticationError("This account has been deactivated.", code="ACCOUNT_DISABLED")
    return session


CurrentSession = Annotated[UserSession, Depends(get_current_session)]


def get_current_user_allow_pending(session: CurrentSession) -> User:
    """Current user, even if they still have to change a temporary password."""
    return session.user


def get_current_user(session: CurrentSession) -> User:
    user = session.user
    if user.must_change_password:
        raise PermissionDenied(
            "You must change your temporary password before continuing.",
            code="PASSWORD_CHANGE_REQUIRED",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentUserAllowPending = Annotated[User, Depends(get_current_user_allow_pending)]


def require(*permissions: P, any_of: bool = False) -> Callable[[User], User]:
    """Dependency factory: `Depends(require(P.USERS_MANAGE))`.

    By default the user needs all listed permissions; with any_of=True, at least one.
    """

    def checker(user: CurrentUser) -> User:
        granted = user.permission_codes
        needed = {p.value for p in permissions}
        ok = bool(needed & granted) if any_of else needed <= granted
        if not ok:
            raise PermissionDenied("You do not have permission to perform this action.")
        return user

    return checker


def get_request_context(request: Request) -> RequestContext:
    return RequestContext.from_request(request)


Ctx = Annotated[RequestContext, Depends(get_request_context)]


def page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


Pagination = Annotated[PageParams, Depends(page_params)]

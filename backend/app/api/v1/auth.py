"""Authentication endpoints.

Access tokens travel in the Authorization header and live only in browser memory.
The refresh token lives in an HttpOnly cookie scoped to /api/v1/auth, so JavaScript
can never read it. Cookie-authenticated endpoints also require the
`X-Requested-With: XMLHttpRequest` header as a CSRF safeguard on top of SameSite=Strict.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response, status

from app.api.deps import (
    Ctx,
    CurrentSession,
    CurrentUserAllowPending,
    DbSession,
    limit_per_ip,
    limit_per_user,
)
from app.core import totp
from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, NotFoundError, RateLimited
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import create_access_token
from app.models import User, UserSession
from app.schemas.auth import (
    ChangePasswordRequest,
    CurrentUser,
    LoginRequest,
    MfaCodeRequest,
    MfaDisableRequest,
    MfaSetupRequest,
    MfaSetupResponse,
    ResetPasswordRequest,
    RoleBrief,
    SessionOut,
    TokenResponse,
)
from app.schemas.common import Message
from app.services import audit_service, auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])

REFRESH_COOKIE = "refresh_token"
COOKIE_PATH = "/api/v1/auth"

login_limiter = SlidingWindowLimiter(
    limit=get_settings().login_rate_limit_per_minute, window_seconds=60
)


def require_xhr(x_requested_with: Annotated[str | None, Header()] = None) -> None:
    if x_requested_with != "XMLHttpRequest":
        raise AuthenticationError("Missing X-Requested-With header", code="CSRF_CHECK_FAILED")


def to_current_user(user: User) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        full_name=user.full_name,
        username=user.username,
        email=user.email,
        phone=user.phone,
        role=RoleBrief.model_validate(user.role),
        permissions=sorted(user.permission_codes),
        must_change_password=user.must_change_password,
        mfa_enabled=user.mfa_enabled,
        last_login_at=user.last_login_at,
    )


def _cookie_secure(request: Request) -> bool:
    """Secure cookies whenever the browser is on HTTPS (directly or via a TLS proxy), even if
    COOKIE_SECURE was left false; COOKIE_SECURE=true forces it on everywhere."""
    return get_settings().cookie_secure or request.url.scheme == "https"


def _token_response(
    request: Request, response: Response, user: User, session: UserSession, refresh: str | None
):
    settings = get_settings()
    access, expires_in = create_access_token(
        user_id=user.id, session_id=session.id, role=user.role.name
    )
    if refresh is not None:
        response.set_cookie(
            REFRESH_COOKIE,
            refresh,
            max_age=settings.refresh_token_days * 86400,
            httponly=True,
            secure=_cookie_secure(request),
            samesite="strict",
            path=COOKIE_PATH,
        )
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(access_token=access, expires_in=expires_in, user=to_current_user(user))


def _clear_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=COOKIE_PATH,
        secure=_cookie_secure(request),
        httponly=True,
        samesite="strict",
    )


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest, request: Request, response: Response, db: DbSession, ctx: Ctx
) -> TokenResponse:
    """Sign in with username (or email) and password."""
    if not login_limiter.hit(ctx.ip_address or "unknown"):
        raise RateLimited("Too many sign-in attempts from this device. Wait a minute and retry.")
    result = auth_service.authenticate(db, body.username, body.password, ctx, otp=body.otp)
    return _token_response(request, response, result.user, result.session, result.refresh_token)


# Refresh is called by the app every ~15 minutes per tab; this only stops floods.
refresh_limit = limit_per_ip(60, 60, "Too many requests. Wait a minute and retry.")
# Stops someone holding a stolen access token from guessing the current password.
change_password_limit = limit_per_user(
    5, 15 * 60, "Too many password change attempts. Wait 15 minutes and retry."
)
# Same for the two-step setup/disable endpoints (they check the password and codes).
mfa_limit = limit_per_user(10, 15 * 60, "Too many attempts. Wait 15 minutes and retry.")


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(require_xhr), Depends(refresh_limit)],
)
def refresh(
    request: Request,
    response: Response,
    db: DbSession,
    ctx: Ctx,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> TokenResponse:
    """Exchange the refresh cookie for a new access token (and a rotated cookie)."""
    try:
        result = auth_service.refresh(db, refresh_token, ctx)
    except AuthenticationError:
        _clear_cookie(request, response)
        raise
    return _token_response(request, response, result.user, result.session, result.refresh_token)


@router.post("/logout", response_model=Message, dependencies=[Depends(require_xhr)])
def logout(
    request: Request, response: Response, session: CurrentSession, db: DbSession, ctx: Ctx
) -> Message:
    auth_service.logout(db, session, ctx)
    _clear_cookie(request, response)
    return Message(message="Signed out")


@router.get("/me", response_model=CurrentUser)
def me(user: CurrentUserAllowPending) -> CurrentUser:
    return to_current_user(user)


@router.post(
    "/change-password", response_model=Message, dependencies=[Depends(change_password_limit)]
)
def change_password(
    body: ChangePasswordRequest,
    session: CurrentSession,
    db: DbSession,
    ctx: Ctx,
) -> Message:
    """Change your own password. Other devices are signed out."""
    auth_service.change_password(
        db, session.user, session, body.current_password, body.new_password, ctx
    )
    return Message(message="Password changed")


@router.post("/reset-password", response_model=Message)
def reset_password(body: ResetPasswordRequest, db: DbSession, ctx: Ctx) -> Message:
    """Set a new password using a one-time link issued by an administrator."""
    if not login_limiter.hit(f"reset:{ctx.ip_address or 'unknown'}"):
        raise RateLimited("Too many attempts. Wait a minute and retry.")
    auth_service.reset_password_with_token(db, body.token, body.new_password, ctx)
    return Message(message="Password set. You can now sign in.")


@router.get("/sessions", response_model=list[SessionOut])
def my_sessions(session: CurrentSession, db: DbSession) -> list[SessionOut]:
    """Devices currently signed in to your account."""
    out = []
    for s in auth_service.active_sessions(db, session.user_id):
        item = SessionOut.model_validate(s)
        item.is_current = s.id == session.id
        out.append(item)
    return out


@router.delete("/sessions/{session_id}", response_model=Message, status_code=status.HTTP_200_OK)
def revoke_my_session(session_id: int, session: CurrentSession, db: DbSession, ctx: Ctx) -> Message:
    """Sign out one of your other devices."""
    target = db.get(UserSession, session_id)
    if target is None or target.user_id != session.user_id or target.revoked_at is not None:
        raise NotFoundError("Session not found")
    target.revoked_at = auth_service.utcnow()
    target.revoked_reason = "revoked_by_user"
    audit_service.record(
        db,
        action="auth.session_revoked",
        actor=session.user,
        ctx=ctx,
        entity_type="user_session",
        entity_id=target.id,
    )
    db.commit()
    return Message(message="Device signed out")


# --- Two-step sign-in ---------------------------------------------------------------------


@router.post("/mfa/setup", response_model=MfaSetupResponse, dependencies=[Depends(mfa_limit)])
def mfa_setup(
    body: MfaSetupRequest, session: CurrentSession, db: DbSession, ctx: Ctx
) -> MfaSetupResponse:
    """Start turning on two-step sign-in: returns a key to add to an authenticator app."""
    user = session.user
    secret = auth_service.start_mfa_setup(db, user, body.password, ctx)
    uri = totp.provisioning_uri(secret, user.username, get_settings().app_name)
    return MfaSetupResponse(secret=secret, otpauth_uri=uri)


@router.post("/mfa/enable", response_model=Message, dependencies=[Depends(mfa_limit)])
def mfa_enable(body: MfaCodeRequest, session: CurrentSession, db: DbSession, ctx: Ctx) -> Message:
    """Finish setup with a code from the app. Your other devices are signed out."""
    auth_service.enable_mfa(db, session.user, session, body.code, ctx)
    return Message(message="Two-step sign-in is on")


@router.post("/mfa/disable", response_model=Message, dependencies=[Depends(mfa_limit)])
def mfa_disable(
    body: MfaDisableRequest, session: CurrentSession, db: DbSession, ctx: Ctx
) -> Message:
    """Turn two-step sign-in off (needs your password and a current code)."""
    auth_service.disable_mfa(db, session.user, body.password, body.code, ctx)
    return Message(message="Two-step sign-in is off")

"""Authentication: login, lockout, session rotation, logout, password change and reset."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.core import totp
from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, ValidationFailed
from app.core.security import (
    generate_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    password_problems,
    verify_password,
)
from app.models import PasswordResetToken, User, UserSession
from app.services import audit_service
from app.services.audit_service import RequestContext

INVALID_CREDENTIALS = "Invalid username or password"

# Verifying against a real hash when the user does not exist keeps response times similar,
# so attackers cannot discover valid usernames by timing.
_DUMMY_HASH = hash_password("dummy-password-for-timing-1")


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class LoginResult:
    user: User
    session: UserSession
    refresh_token: str | None  # None = keep the cookie the client already has


# --- Login --------------------------------------------------------------------


def authenticate(
    db: Session,
    username: str,
    password: str,
    ctx: RequestContext,
    otp: str | None = None,
) -> LoginResult:
    ident = username.strip().lower()
    user = db.scalar(
        select(User).where(or_(func.lower(User.username) == ident, func.lower(User.email) == ident))
    )
    now = utcnow()

    if user is None:
        verify_password(password, _DUMMY_HASH)
        _log_failure(db, None, ctx, f"unknown user '{ident[:64]}'")
        raise AuthenticationError(INVALID_CREDENTIALS)

    if user.locked_until and user.locked_until > now:
        _log_failure(db, user, ctx, "account locked")
        minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise AuthenticationError(
            f"Too many failed attempts. Try again in about {minutes} minute(s) "
            "or ask an administrator to unlock the account.",
            code="ACCOUNT_LOCKED",
        )

    if not verify_password(password, user.password_hash):
        _count_failure(db, user, ctx, "wrong password")
        raise AuthenticationError(INVALID_CREDENTIALS)

    if not user.is_active:
        _log_failure(db, user, ctx, "account deactivated")
        raise AuthenticationError("This account has been deactivated.", code="ACCOUNT_DISABLED")

    if user.mfa_enabled:
        if not otp:
            # The password was right; ask for the second step. Not counted as a failure.
            raise AuthenticationError(
                "Enter the 6-digit code from your authenticator app.", code="MFA_REQUIRED"
            )
        step = totp.verify(user.totp_secret or "", otp, last_used_step=user.totp_last_step)
        if step is None:
            # Wrong or reused codes count towards the same lockout as wrong passwords.
            _count_failure(db, user, ctx, "wrong two-step code")
            raise AuthenticationError(
                "That code is not valid. Use the newest code from your app.", code="MFA_INVALID"
            )
        user.totp_last_step = step

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    session, token = _create_session(db, user, ctx)
    audit_service.record(
        db, action="auth.login", actor=user, ctx=ctx, entity_type="user", entity_id=user.id
    )
    db.commit()
    return LoginResult(user=user, session=session, refresh_token=token)


def _count_failure(db: Session, user: User, ctx: RequestContext, reason: str) -> None:
    """Record a failed attempt (wrong password or code); lock the account after too many."""
    settings = get_settings()
    user.failed_login_count += 1
    if user.failed_login_count >= settings.login_max_failures:
        user.locked_until = utcnow() + timedelta(minutes=settings.lockout_minutes)
        user.failed_login_count = 0
        reason = f"{reason}; account locked"
        audit_service.record(
            db,
            action="auth.account_locked",
            actor=user,
            ctx=ctx,
            entity_type="user",
            entity_id=user.id,
        )
    _log_failure(db, user, ctx, reason)


def _log_failure(db: Session, user: User | None, ctx: RequestContext, reason: str) -> None:
    audit_service.record(
        db,
        action="auth.login_failed",
        actor=user,
        ctx=ctx,
        entity_type="user",
        entity_id=user.id if user else None,
        details=reason,
    )
    db.commit()


def _create_session(db: Session, user: User, ctx: RequestContext) -> tuple[UserSession, str]:
    settings = get_settings()
    now = utcnow()
    token = generate_token()
    session = UserSession(
        user_id=user.id,
        refresh_token_hash=hash_token(token),
        user_agent=ctx.user_agent,
        ip_address=ctx.ip_address,
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(days=settings.refresh_token_days),
    )
    db.add(session)
    db.flush()
    return session, token


# --- Refresh / logout ------------------------------------------------------------


def refresh(db: Session, refresh_token: str | None, ctx: RequestContext) -> LoginResult:
    """Rotate a refresh token.

    Each refresh token works once. Presenting an already-rotated token (outside a short
    grace window for simultaneous browser tabs) is treated as theft: the session is revoked.
    """
    if not refresh_token:
        raise AuthenticationError("Not signed in")
    settings = get_settings()
    now = utcnow()
    token_hash = hash_token(refresh_token)

    session = db.scalar(
        select(UserSession)
        .where(UserSession.refresh_token_hash == token_hash)
        .with_for_update(of=UserSession)
    )
    if session is not None:
        _ensure_usable(session, now)
        new_token = generate_token()
        session.previous_token_hash = token_hash
        session.refresh_token_hash = hash_token(new_token)
        session.rotated_at = now
        session.last_used_at = now
        session.ip_address = ctx.ip_address or session.ip_address
        db.commit()
        return LoginResult(user=session.user, session=session, refresh_token=new_token)

    session = db.scalar(
        select(UserSession)
        .where(UserSession.previous_token_hash == token_hash)
        .with_for_update(of=UserSession)
    )
    if session is None:
        raise AuthenticationError("Session not found. Please sign in again.")
    grace = timedelta(seconds=settings.refresh_reuse_grace_seconds)
    if session.revoked_at is None and session.rotated_at and now - session.rotated_at <= grace:
        # Another tab rotated a moment ago; its new cookie is already in the browser.
        _ensure_usable(session, now)
        return LoginResult(user=session.user, session=session, refresh_token=None)

    if session.revoked_at is None:
        session.revoked_at = now
        session.revoked_reason = "token_reuse"
        audit_service.record(
            db,
            action="auth.refresh_token_reuse",
            actor=session.user,
            ctx=ctx,
            entity_type="user_session",
            entity_id=session.id,
            details="A previously used refresh token was presented; session revoked.",
        )
        db.commit()
    raise AuthenticationError("Session is no longer valid. Please sign in again.")


def _ensure_usable(session: UserSession, now: datetime) -> None:
    if session.revoked_at is not None:
        raise AuthenticationError("Session has been signed out. Please sign in again.")
    if session.expires_at <= now:
        raise AuthenticationError("Session expired. Please sign in again.")
    if not session.user.is_active:
        raise AuthenticationError("This account has been deactivated.", code="ACCOUNT_DISABLED")


def logout(db: Session, session: UserSession, ctx: RequestContext) -> None:
    if session.revoked_at is None:
        session.revoked_at = utcnow()
        session.revoked_reason = "logout"
    audit_service.record(
        db,
        action="auth.logout",
        actor=session.user,
        ctx=ctx,
        entity_type="user_session",
        entity_id=session.id,
    )
    db.commit()


def revoke_user_sessions(
    db: Session, user_id: int, reason: str, *, except_session_id: int | None = None
) -> int:
    stmt = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoked_reason=reason)
    )
    if except_session_id is not None:
        stmt = stmt.where(UserSession.id != except_session_id)
    return db.execute(stmt).rowcount or 0


def active_sessions(db: Session, user_id: int) -> list[UserSession]:
    return list(
        db.scalars(
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > utcnow(),
            )
            .order_by(UserSession.last_used_at.desc())
        )
    )


# --- Passwords --------------------------------------------------------------------


def validate_new_password(password: str, username: str) -> None:
    problems = password_problems(password, username=username)
    if problems:
        raise ValidationFailed(
            "Password " + "; ".join(problems),
            details=[{"field": "new_password", "message": p} for p in problems],
        )


def change_password(
    db: Session,
    user: User,
    current_session: UserSession,
    current_password: str,
    new_password: str,
    ctx: RequestContext,
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise ValidationFailed(
            "Current password is incorrect",
            details=[{"field": "current_password", "message": "is incorrect"}],
        )
    if verify_password(new_password, user.password_hash):
        raise ValidationFailed(
            "New password must be different from the current one",
            details=[{"field": "new_password", "message": "must be different"}],
        )
    validate_new_password(new_password, user.username)
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.password_changed_at = utcnow()
    revoked = revoke_user_sessions(
        db, user.id, "password_changed", except_session_id=current_session.id
    )
    audit_service.record(
        db,
        action="auth.password_changed",
        actor=user,
        ctx=ctx,
        entity_type="user",
        entity_id=user.id,
        details=f"{revoked} other session(s) signed out",
    )
    db.commit()


def issue_reset_token(
    db: Session, user: User, actor: User, ctx: RequestContext, *, note: str | None = None
) -> tuple[str, datetime]:
    """Create a single-use reset/setup token. Earlier unused tokens for the user stop working."""
    settings = get_settings()
    now = utcnow()
    db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now, note="superseded")
    )
    token = generate_token()
    expires = now + timedelta(minutes=settings.password_reset_minutes)
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(token),
            created_by_id=actor.id,
            created_at=now,
            expires_at=expires,
            note=note,
        )
    )
    audit_service.record(
        db,
        action="user.password_reset_issued",
        actor=actor,
        ctx=ctx,
        entity_type="user",
        entity_id=user.id,
        details=note,
    )
    return token, expires


def reset_password_with_token(
    db: Session, token: str, new_password: str, ctx: RequestContext
) -> User:
    now = utcnow()
    record = db.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == hash_token(token))
        .with_for_update()
    )
    if record is None or record.used_at is not None or record.expires_at <= now:
        raise ValidationFailed(
            "This reset link is invalid or has expired. Ask an administrator for a new one.",
            code="INVALID_RESET_TOKEN",
        )
    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise ValidationFailed("This account is not active.", code="INVALID_RESET_TOKEN")
    validate_new_password(new_password, user.username)

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.password_changed_at = now
    user.failed_login_count = 0
    user.locked_until = None
    record.used_at = now
    revoke_user_sessions(db, user.id, "password_reset")
    audit_service.record(
        db,
        action="auth.password_reset",
        actor=user,
        ctx=ctx,
        entity_type="user",
        entity_id=user.id,
    )
    db.commit()
    return user


# --- Two-step sign-in (TOTP) -------------------------------------------------------------


def _require_password(user: User, password: str) -> None:
    if not verify_password(password, user.password_hash):
        raise ValidationFailed(
            "Your current password is not correct.",
            details=[{"field": "password", "message": "incorrect"}],
            code="WRONG_PASSWORD",
        )


def start_mfa_setup(db: Session, user: User, password: str, ctx: RequestContext) -> str:
    """Create a new secret for the user to add to their app. Not active until confirmed."""
    _require_password(user, password)
    if user.mfa_enabled:
        raise ValidationFailed("Two-step sign-in is already on.", code="MFA_ALREADY_ENABLED")
    user.totp_secret = totp.generate_secret()
    user.totp_enabled_at = None
    user.totp_last_step = None
    audit_service.record(
        db,
        action="auth.mfa_setup_started",
        actor=user,
        ctx=ctx,
        entity_type="user",
        entity_id=user.id,
    )
    db.commit()
    return user.totp_secret


def enable_mfa(
    db: Session, user: User, session: UserSession, code: str, ctx: RequestContext
) -> int:
    """Confirm setup with a code from the app. Signs out the user's other devices."""
    if user.mfa_enabled:
        raise ValidationFailed("Two-step sign-in is already on.", code="MFA_ALREADY_ENABLED")
    if not user.totp_secret:
        raise ValidationFailed("Start the setup first.", code="MFA_NOT_STARTED")
    step = totp.verify(user.totp_secret, code, last_used_step=None)
    if step is None:
        raise ValidationFailed(
            "That code is not valid. Check the time on your phone and try the newest code.",
            details=[{"field": "code", "message": "invalid"}],
            code="MFA_INVALID",
        )
    user.totp_enabled_at = utcnow()
    user.totp_last_step = step
    revoked = revoke_user_sessions(db, user.id, "mfa_enabled", except_session_id=session.id)
    audit_service.record(
        db, action="auth.mfa_enabled", actor=user, ctx=ctx, entity_type="user", entity_id=user.id
    )
    db.commit()
    return revoked


def disable_mfa(db: Session, user: User, password: str, code: str, ctx: RequestContext) -> None:
    """Turning it off needs both the password and a current code."""
    _require_password(user, password)
    if not user.mfa_enabled:
        raise ValidationFailed("Two-step sign-in is not on.", code="MFA_NOT_ENABLED")
    step = totp.verify(user.totp_secret or "", code, last_used_step=user.totp_last_step)
    if step is None:
        raise ValidationFailed(
            "That code is not valid.",
            details=[{"field": "code", "message": "invalid"}],
            code="MFA_INVALID",
        )
    _clear_mfa(user)
    audit_service.record(
        db, action="auth.mfa_disabled", actor=user, ctx=ctx, entity_type="user", entity_id=user.id
    )
    db.commit()


def _clear_mfa(user: User) -> None:
    user.totp_secret = None
    user.totp_enabled_at = None
    user.totp_last_step = None

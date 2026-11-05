"""Password hashing, JWT access tokens and opaque refresh tokens."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

# Argon2id with library defaults (memory-hard; ~50 ms on a laptop).
_hasher = PasswordHasher()

# A small blocklist of passwords that are common in breach dumps or obvious for a shop.
COMMON_PASSWORDS = frozenset(
    {
        "password",
        "password1",
        "password123",
        "12345678",
        "123456789",
        "1234567890",
        "qwerty123",
        "qwertyuiop",
        "iloveyou",
        "admin123",
        "administrator",
        "letmein1",
        "welcome1",
        "welcome123",
        "supermarket",
        "inventory",
        "changeme",
        "passw0rd",
        "11111111",
        "00000000",
        "abc12345",
        "kenya2024",
        "kenya2025",
        "kenya2026",
    }
)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_problems(password: str, *, username: str | None = None) -> list[str]:
    """Return human-readable reasons a password is unacceptable (empty list = OK)."""
    settings = get_settings()
    problems: list[str] = []
    if len(password) < settings.password_min_length:
        problems.append(f"must be at least {settings.password_min_length} characters")
    if len(password) > 128:
        problems.append("must be at most 128 characters")
    if password.lower() in COMMON_PASSWORDS:
        problems.append("is too common")
    if username and username.lower() in password.lower():
        problems.append("must not contain the username")
    if password.isdigit() or password.isalpha():
        problems.append("must mix letters with numbers or symbols")
    return problems


# --- Access tokens (JWT) -----------------------------------------------------


def create_access_token(*, user_id: int, session_id: int, role: str) -> tuple[str, int]:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_in = settings.access_token_minutes * 60
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sid": session_id,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError on any problem (expired, bad signature, wrong type)."""
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["sub", "sid", "exp", "type"]},
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return payload


# --- Opaque tokens (refresh, password reset) ---------------------------------


def generate_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

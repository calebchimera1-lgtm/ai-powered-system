"""Unit tests for password hashing, password policy and tokens."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_token,
    hash_password,
    hash_token,
    password_problems,
    verify_password,
)


def test_password_hash_is_argon2_and_verifies() -> None:
    h = hash_password("Correct-Horse-9")
    assert h.startswith("$argon2id$")
    assert "Correct-Horse-9" not in h
    assert verify_password("Correct-Horse-9", h)
    assert not verify_password("correct-horse-9", h)


def test_same_password_hashes_differently() -> None:
    assert hash_password("Same-Pass-1") != hash_password("Same-Pass-1")


def test_verify_handles_garbage_hash() -> None:
    assert verify_password("anything", "not-a-hash") is False


@pytest.mark.parametrize(
    ("password", "fragment"),
    [
        ("short1", "at least"),
        ("password123", "too common"),
        ("abcdefghij", "mix letters"),
        ("1234567890123", "mix letters"),
        ("jdoe-secret-9", "username"),
    ],
)
def test_password_policy_rejects_weak(password: str, fragment: str) -> None:
    problems = password_problems(password, username="jdoe")
    assert any(fragment in p for p in problems), problems


def test_password_policy_accepts_reasonable() -> None:
    assert password_problems("Mumias-Sugar-2kg", username="jdoe") == []


def test_access_token_roundtrip() -> None:
    token, expires_in = create_access_token(user_id=7, session_id=3, role="cashier")
    payload = decode_access_token(token)
    assert payload["sub"] == "7"
    assert payload["sid"] == 3
    assert payload["role"] == "cashier"
    assert expires_in == get_settings().access_token_minutes * 60


def test_expired_access_token_rejected() -> None:
    s = get_settings()
    past = datetime.now(UTC) - timedelta(minutes=1)
    token = jwt.encode(
        {"sub": "1", "sid": 1, "type": "access", "exp": past}, s.jwt_secret, algorithm="HS256"
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)


def test_token_with_wrong_secret_rejected() -> None:
    token = jwt.encode(
        {"sub": "1", "sid": 1, "type": "access", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        "some-other-secret-value",
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(token)


def test_non_access_token_type_rejected() -> None:
    s = get_settings()
    token = jwt.encode(
        {"sub": "1", "sid": 1, "type": "refresh", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        s.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)


def test_alg_none_rejected() -> None:
    token = jwt.encode(
        {"sub": "1", "sid": 1, "type": "access", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        key=None,
        algorithm="none",
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)


def test_opaque_tokens_are_random_and_hash_stable() -> None:
    a, b = generate_token(), generate_token()
    assert a != b and len(a) >= 60
    assert hash_token(a) == hash_token(a)
    assert len(hash_token(a)) == 64


def test_rate_limiter_blocks_after_limit() -> None:
    limiter = SlidingWindowLimiter(limit=3, window_seconds=60)
    assert all(limiter.hit("ip") for _ in range(3))
    assert limiter.hit("ip") is False
    assert limiter.hit("other-ip") is True

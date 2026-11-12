"""Time-based one-time passwords (RFC 6238) for two-step sign-in.

Standard authenticator-app parameters: HMAC-SHA1, 6 digits, 30-second steps. Implemented
with the standard library only. A code is accepted for the current step and one step
either side (clock drift), and each step can be used only once per account (replay guard).
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

STEP_SECONDS = 30
DIGITS = 6
DRIFT_STEPS = 1


def generate_secret() -> str:
    """A new 160-bit shared secret, base32 encoded (what authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def _key(secret: str) -> bytes:
    cleaned = secret.replace(" ", "").upper()
    return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))


def code_at(secret: str, step: int, digits: int = DIGITS, digest: str = "sha1") -> str:
    mac = hmac.new(_key(secret), struct.pack(">Q", step), getattr(hashlib, digest)).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP_SECONDS)


def verify(
    secret: str, code: str, *, last_used_step: int | None, now: float | None = None
) -> int | None:
    """Return the matched time step, or None. Steps at or before `last_used_step` are refused,
    so an intercepted code cannot be replayed."""
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    step = current_step(now)
    for candidate in range(step - DRIFT_STEPS, step + DRIFT_STEPS + 1):
        if last_used_step is not None and candidate <= last_used_step:
            continue
        if hmac.compare_digest(code_at(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    """otpauth:// link that authenticator apps understand (also what a QR code would hold)."""
    label = quote(f"{issuer}:{account}")
    query = urlencode(
        {"secret": secret, "issuer": issuer, "digits": DIGITS, "period": STEP_SECONDS}
    )
    return f"otpauth://totp/{label}?{query}"

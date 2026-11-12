"""Two-step sign-in (TOTP): setup, sign-in, replay protection, lockout, disable, admin reset."""

import base64

from fastapi.testclient import TestClient

from app.core import totp
from tests.conftest import PASSWORD, login

LOGIN = "/api/v1/auth/login"


def _code(secret: str, offset_steps: int = 0) -> str:
    return totp.code_at(secret, totp.current_step() + offset_steps)


def _enable(client: TestClient, headers: dict[str, str]) -> str:
    r = client.post("/api/v1/auth/mfa/setup", headers=headers, json={"password": PASSWORD})
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    assert r.json()["otpauth_uri"].startswith("otpauth://totp/")
    r = client.post("/api/v1/auth/mfa/enable", headers=headers, json={"code": _code(secret)})
    assert r.status_code == 200, r.text
    return secret


def test_rfc6238_reference_vectors() -> None:
    secret = base64.b32encode(b"12345678901234567890").decode()
    for t, expected in {59: "94287082", 1111111109: "07081804", 2000000000: "69279037"}.items():
        assert totp.code_at(secret, t // 30, digits=8) == expected


def test_setup_needs_the_current_password(client: TestClient, auth_headers) -> None:
    _, h = auth_headers("cashier")
    r = client.post("/api/v1/auth/mfa/setup", headers=h, json={"password": "wrong-pass-1"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "WRONG_PASSWORD"


def test_setup_is_not_active_until_confirmed(client: TestClient, auth_headers) -> None:
    user, h = auth_headers("cashier")
    client.post("/api/v1/auth/mfa/setup", headers=h, json={"password": PASSWORD})
    # Not confirmed yet: password alone still signs in.
    assert (
        client.post(LOGIN, json={"username": user.username, "password": PASSWORD}).status_code
        == 200
    )
    bad = client.post("/api/v1/auth/mfa/enable", headers=h, json={"code": "000000"})
    assert bad.status_code == 422


def test_sign_in_requires_a_valid_code_once_enabled(client: TestClient, auth_headers) -> None:
    user, h = auth_headers("store_manager")
    secret = _enable(client, h)
    assert client.get("/api/v1/auth/me", headers=h).json()["mfa_enabled"] is True

    creds = {"username": user.username, "password": PASSWORD}
    r = client.post(LOGIN, json=creds)
    assert r.status_code == 401 and r.json()["error"]["code"] == "MFA_REQUIRED"
    assert "set-cookie" not in r.headers  # no session before the second step

    r = client.post(LOGIN, json={**creds, "otp": "123456"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "MFA_INVALID"

    # The code used to enable is spent; the next step's code works once.
    code = _code(secret, 1)
    assert client.post(LOGIN, json={**creds, "otp": code}).status_code == 200
    replay = client.post(LOGIN, json={**creds, "otp": code})
    assert replay.status_code == 401 and replay.json()["error"]["code"] == "MFA_INVALID"


def test_wrong_password_never_reveals_that_two_step_is_on(client: TestClient, auth_headers) -> None:
    user, h = auth_headers("cashier")
    _enable(client, h)
    r = client.post(LOGIN, json={"username": user.username, "password": "Wrong-Pass-99"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_wrong_codes_lock_the_account(client: TestClient, auth_headers) -> None:
    user, h = auth_headers("cashier")
    _enable(client, h)
    creds = {"username": user.username, "password": PASSWORD, "otp": "000000"}
    codes = [client.post(LOGIN, json=creds).json()["error"]["code"] for _ in range(6)]
    assert codes[:5] == ["MFA_INVALID"] * 5 and codes[5] == "ACCOUNT_LOCKED"


def test_enabling_signs_out_other_devices(client: TestClient, auth_headers) -> None:
    user, h = auth_headers("cashier")
    other_device = login(client, user.username)
    _enable(client, h)
    assert client.get("/api/v1/auth/me", headers=other_device).status_code == 401
    assert client.get("/api/v1/auth/me", headers=h).status_code == 200


def test_disable_needs_password_and_code(client: TestClient, auth_headers) -> None:
    user, h = auth_headers("cashier")
    secret = _enable(client, h)
    url = "/api/v1/auth/mfa/disable"
    assert (
        client.post(url, headers=h, json={"password": PASSWORD, "code": "000000"}).status_code
        == 422
    )
    assert (
        client.post(
            url, headers=h, json={"password": "Nope-123x", "code": _code(secret, 1)}
        ).status_code
        == 422
    )
    assert (
        client.post(
            url, headers=h, json={"password": PASSWORD, "code": _code(secret, 1)}
        ).status_code
        == 200
    )
    assert (
        client.post(LOGIN, json={"username": user.username, "password": PASSWORD}).status_code
        == 200
    )


def test_secret_is_never_exposed_after_setup(client: TestClient, auth_headers) -> None:
    user, h = auth_headers("cashier")
    secret = _enable(client, h)
    _, admin = auth_headers("super_admin")
    for body in (
        client.get("/api/v1/auth/me", headers=h).text,
        client.get(f"/api/v1/users/{user.id}", headers=admin).text,
        client.get("/api/v1/users", headers=admin).text,
        client.get("/api/v1/audit-logs", headers=admin).text,
    ):
        assert secret not in body


def test_super_admin_can_reset_a_lost_phone(client: TestClient, auth_headers) -> None:
    user, h = auth_headers("cashier")
    _enable(client, h)
    _, admin = auth_headers("super_admin")
    r = client.post(f"/api/v1/users/{user.id}/reset-mfa", headers=admin)
    assert r.status_code == 200 and r.json()["mfa_enabled"] is False
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401  # signed out everywhere
    assert (
        client.post(LOGIN, json={"username": user.username, "password": PASSWORD}).status_code
        == 200
    )


def test_only_user_managers_can_reset_mfa(client: TestClient, auth_headers) -> None:
    user, _ = auth_headers("cashier")
    _, manager = auth_headers("store_manager")
    assert client.post(f"/api/v1/users/{user.id}/reset-mfa", headers=manager).status_code == 403

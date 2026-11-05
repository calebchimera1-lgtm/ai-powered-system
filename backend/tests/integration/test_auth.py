"""Authentication API tests: login, lockout, refresh rotation, logout, passwords, sessions."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, User, UserSession
from tests.conftest import PASSWORD, XHR, login

LOGIN = "/api/v1/auth/login"


def actions(db: Session) -> list[str]:
    db.expire_all()
    return [a.action for a in db.scalars(select(AuditLog).order_by(AuditLog.id))]


# --- Login ---------------------------------------------------------------------


def test_login_success_returns_token_user_and_cookie(client: TestClient, make_user, db) -> None:
    make_user("inventory_officer", username="officer")
    resp = client.post(LOGIN, json={"username": "officer", "password": PASSWORD})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer" and body["access_token"]
    assert body["user"]["role"]["name"] == "inventory_officer"
    assert "invoices:upload" in body["user"]["permissions"]
    assert "users:manage" not in body["user"]["permissions"]
    cookie = resp.headers["set-cookie"]
    assert "refresh_token=" in cookie and "HttpOnly" in cookie
    assert "Path=/api/v1/auth" in cookie and "SameSite=strict" in cookie
    assert "auth.login" in actions(db)


def test_login_by_email_case_insensitive(client: TestClient, make_user) -> None:
    make_user("cashier", username="mary")
    resp = client.post(LOGIN, json={"username": "MARY@test.local", "password": PASSWORD})
    assert resp.status_code == 200


def test_login_wrong_password_and_unknown_user_same_message(client: TestClient, make_user) -> None:
    make_user("cashier", username="john")
    wrong = client.post(LOGIN, json={"username": "john", "password": "Nope-12345"})
    unknown = client.post(LOGIN, json={"username": "ghost", "password": "Nope-12345"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_account_locks_after_repeated_failures(client: TestClient, make_user, db) -> None:
    user = make_user("cashier", username="locky")
    for _ in range(5):
        r = client.post(LOGIN, json={"username": "locky", "password": "Wrong-pass-1"})
        assert r.status_code == 401
    # Even the correct password is refused while locked.
    r = client.post(LOGIN, json={"username": "locky", "password": PASSWORD})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "ACCOUNT_LOCKED"
    db.refresh(user)
    assert user.locked_until is not None
    assert "auth.account_locked" in actions(db)


def test_lock_expires(client: TestClient, make_user, db) -> None:
    user = make_user("cashier", username="expired_lock")
    user.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert (
        client.post(LOGIN, json={"username": "expired_lock", "password": PASSWORD}).status_code
        == 200
    )


def test_inactive_user_cannot_login(client: TestClient, make_user) -> None:
    make_user("cashier", username="gone", is_active=False)
    r = client.post(LOGIN, json={"username": "gone", "password": PASSWORD})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "ACCOUNT_DISABLED"


def test_login_rate_limited_per_ip(client: TestClient) -> None:
    codes = [
        client.post(LOGIN, json={"username": f"u{i}", "password": "x"}).status_code
        for i in range(21)
    ]
    assert codes[-1] == 429


def test_login_validation_error_shape(client: TestClient) -> None:
    r = client.post(LOGIN, json={"username": ""})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert {d["field"] for d in err["details"]} >= {"username", "password"}


# --- Access control on protected endpoints -----------------------------------


def test_me_requires_token(client: TestClient) -> None:
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_me_with_garbage_token(client: TestClient) -> None:
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer abc.def.ghi"})
    assert r.status_code == 401


def test_me_returns_profile(client: TestClient, auth_headers) -> None:
    user, headers = auth_headers("store_manager")
    r = client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["username"] == user.username
    assert "password_hash" not in r.text


# --- Refresh rotation -----------------------------------------------------------


def test_refresh_rotates_cookie_and_old_token_reuse_revokes(
    client: TestClient, make_user, db
) -> None:
    make_user("cashier", username="rot")
    client.post(LOGIN, json={"username": "rot", "password": PASSWORD})
    first = client.cookies.get("refresh_token")

    r = client.post("/api/v1/auth/refresh", headers=XHR)
    assert r.status_code == 200 and r.json()["access_token"]
    second = client.cookies.get("refresh_token")
    assert second and second != first

    # Simulate an attacker replaying the first token after the grace window.
    session = db.scalar(select(UserSession))
    session.rotated_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()
    client.cookies.set("refresh_token", first, path="/api/v1/auth")
    r = client.post("/api/v1/auth/refresh", headers=XHR)
    assert r.status_code == 401

    # The whole session is now revoked: the legitimate (second) token stops working too.
    client.cookies.set("refresh_token", second, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh", headers=XHR).status_code == 401
    db.expire_all()
    assert db.scalar(select(UserSession)).revoked_reason == "token_reuse"
    assert "auth.refresh_token_reuse" in actions(db)


def test_refresh_reuse_within_grace_window_is_tolerated(client: TestClient, make_user) -> None:
    make_user("cashier", username="tabs")
    client.post(LOGIN, json={"username": "tabs", "password": PASSWORD})
    first = client.cookies.get("refresh_token")
    assert client.post("/api/v1/auth/refresh", headers=XHR).status_code == 200
    second = client.cookies.get("refresh_token")
    client.cookies.set("refresh_token", first, path="/api/v1/auth")  # second tab, old cookie
    r = client.post("/api/v1/auth/refresh", headers=XHR)
    assert r.status_code == 200
    assert "set-cookie" not in r.headers  # does not rotate again
    client.cookies.set("refresh_token", second, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh", headers=XHR).status_code == 200


def test_refresh_requires_xhr_header(client: TestClient, make_user) -> None:
    make_user("cashier", username="csrf")
    client.post(LOGIN, json={"username": "csrf", "password": PASSWORD})
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "CSRF_CHECK_FAILED"


def test_refresh_without_cookie(client: TestClient) -> None:
    assert client.post("/api/v1/auth/refresh", headers=XHR).status_code == 401


# --- Logout and sessions ------------------------------------------------------


def test_logout_revokes_access_immediately(client: TestClient, make_user) -> None:
    make_user("cashier", username="bye")
    headers = login(client, "bye")
    r = client.post("/api/v1/auth/logout", headers={**headers, **XHR})
    assert r.status_code == 200
    # Same (still unexpired) JWT no longer works because its session is revoked.
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert client.post("/api/v1/auth/refresh", headers=XHR).status_code == 401


def test_list_and_revoke_own_sessions(client: TestClient, make_user) -> None:
    make_user("cashier", username="multi")
    h1 = login(client, "multi")
    h2 = login(client, "multi")
    sessions = client.get("/api/v1/auth/sessions", headers=h1).json()
    assert len(sessions) == 2
    other = next(s for s in sessions if not s["is_current"])
    assert client.delete(f"/api/v1/auth/sessions/{other['id']}", headers=h1).status_code == 200
    assert client.get("/api/v1/auth/me", headers=h2).status_code == 401
    assert client.get("/api/v1/auth/me", headers=h1).status_code == 200


def test_cannot_revoke_someone_elses_session(client: TestClient, make_user, db) -> None:
    make_user("cashier", username="a1")
    make_user("cashier", username="b1")
    ha = login(client, "a1")
    login(client, "b1")
    b_session = db.scalar(select(UserSession).join(User).where(User.username == "b1"))
    assert client.delete(f"/api/v1/auth/sessions/{b_session.id}", headers=ha).status_code == 404


# --- Passwords ------------------------------------------------------------------


def test_change_password_signs_out_other_devices(client: TestClient, make_user) -> None:
    make_user("cashier", username="chg")
    h1 = login(client, "chg")
    h2 = login(client, "chg")
    r = client.post(
        "/api/v1/auth/change-password",
        headers=h1,
        json={"current_password": PASSWORD, "new_password": "Brand-New-Pass-7"},
    )
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/auth/me", headers=h1).status_code == 200
    assert client.get("/api/v1/auth/me", headers=h2).status_code == 401
    assert client.post(LOGIN, json={"username": "chg", "password": PASSWORD}).status_code == 401
    assert (
        client.post(LOGIN, json={"username": "chg", "password": "Brand-New-Pass-7"}).status_code
        == 200
    )


def test_change_password_rejects_wrong_current_and_weak_new(client: TestClient, make_user) -> None:
    make_user("cashier", username="weak")
    h = login(client, "weak")
    r = client.post(
        "/api/v1/auth/change-password",
        headers=h,
        json={"current_password": "wrong-Pass-1", "new_password": "Brand-New-Pass-7"},
    )
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "current_password"
    r = client.post(
        "/api/v1/auth/change-password",
        headers=h,
        json={"current_password": PASSWORD, "new_password": "password123"},
    )
    assert r.status_code == 422 and "too common" in r.json()["error"]["message"]


def test_must_change_password_blocks_other_endpoints(client: TestClient, make_user) -> None:
    make_user("super_admin", username="temp", must_change_password=True)
    h = login(client, "temp")
    assert client.get("/api/v1/auth/me", headers=h).json()["must_change_password"] is True
    r = client.get("/api/v1/users", headers=h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"
    client.post(
        "/api/v1/auth/change-password",
        headers=h,
        json={"current_password": PASSWORD, "new_password": "Brand-New-Pass-7"},
    )
    assert client.get("/api/v1/users", headers=h).status_code == 200

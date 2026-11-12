"""User administration and role-based access control tests."""

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import AuditLog, User
from tests.conftest import PASSWORD, login

USERS = "/api/v1/users"


def new_user(**overrides):
    body = {
        "full_name": "Grace Njeri",
        "username": "gnjeri",
        "email": "grace@example.co.ke",
        "phone": "+254712345678",
        "role": "cashier",
        "password": "Till-Number-42",
    }
    body.update(overrides)
    return body


def token_from(url: str) -> str:
    return parse_qs(urlparse(url).fragment)["token"][0]


# --- RBAC -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "list_status", "create_status"),
    [
        ("super_admin", 200, 201),
        ("store_manager", 200, 403),
        ("inventory_officer", 403, 403),
        ("cashier", 403, 403),
    ],
)
def test_user_endpoints_respect_roles(
    client: TestClient, auth_headers, role, list_status, create_status
) -> None:
    _, h = auth_headers(role)
    assert client.get(USERS, headers=h).status_code == list_status
    assert client.post(USERS, headers=h, json=new_user()).status_code == create_status


@pytest.mark.parametrize(
    ("role", "status"),
    [("super_admin", 200), ("store_manager", 403), ("inventory_officer", 403), ("cashier", 403)],
)
def test_audit_log_admin_only(client: TestClient, auth_headers, role, status) -> None:
    _, h = auth_headers(role)
    assert client.get("/api/v1/audit-logs", headers=h).status_code == status


def test_roles_endpoint_lists_four_roles_with_permissions(client: TestClient, auth_headers) -> None:
    _, h = auth_headers("store_manager")
    roles = client.get("/api/v1/roles", headers=h).json()
    assert [r["name"] for r in roles] == [
        "super_admin",
        "store_manager",
        "inventory_officer",
        "cashier",
    ]
    cashier = roles[-1]
    assert {p["code"] for p in cashier["permissions"]} >= {"sales:create", "products:read"}


# --- Create ------------------------------------------------------------------------


def test_admin_creates_each_role_and_new_user_must_change_password(
    client: TestClient, auth_headers
) -> None:
    _, h = auth_headers("super_admin")
    for i, role in enumerate(["super_admin", "store_manager", "inventory_officer", "cashier"]):
        r = client.post(
            USERS,
            headers=h,
            json=new_user(username=f"staff{i}", email=f"staff{i}@example.com", role=role),
        )
        assert r.status_code == 201, r.text
        assert r.json()["user"]["role"]["name"] == role
        assert r.json()["setup_url"] is None

    me = login(client, "staff3", "Till-Number-42")
    assert client.get("/api/v1/auth/me", headers=me).json()["must_change_password"] is True


def test_create_without_password_returns_setup_link_that_works_once(
    client: TestClient, auth_headers
) -> None:
    _, h = auth_headers("super_admin")
    body = new_user()
    body.pop("password")
    r = client.post(USERS, headers=h, json=body)
    assert r.status_code == 201
    url = r.json()["setup_url"]
    assert url.startswith("http://frontend.test/reset-password#token=")
    assert "?" not in url  # never in the query string, which web servers log
    token = token_from(url)

    r = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "My-Own-Pass-9"}
    )
    assert r.status_code == 200, r.text
    h2 = login(client, "gnjeri", "My-Own-Pass-9")
    assert client.get("/api/v1/auth/me", headers=h2).json()["must_change_password"] is False

    again = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "Other-Pass-99"}
    )
    assert again.status_code == 422 and again.json()["error"]["code"] == "INVALID_RESET_TOKEN"


def test_create_rejects_duplicates_case_insensitively(client: TestClient, auth_headers) -> None:
    _, h = auth_headers("super_admin")
    assert client.post(USERS, headers=h, json=new_user()).status_code == 201
    r = client.post(USERS, headers=h, json=new_user(username="GNJERI", email="x@example.com"))
    assert r.status_code == 409 and r.json()["error"]["details"][0]["field"] == "username"
    r = client.post(USERS, headers=h, json=new_user(username="other", email="GRACE@example.co.ke"))
    assert r.status_code == 409 and r.json()["error"]["details"][0]["field"] == "email"


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"username": "a b"}, "username"),
        ({"email": "not-an-email"}, "email"),
        ({"phone": "call me"}, "phone"),
        ({"full_name": "A"}, "full_name"),
    ],
)
def test_create_validates_fields(client: TestClient, auth_headers, override, field) -> None:
    _, h = auth_headers("super_admin")
    r = client.post(USERS, headers=h, json=new_user(**override))
    assert r.status_code == 422
    assert field in {d["field"] for d in r.json()["error"]["details"]}


def test_create_rejects_unknown_role_and_weak_password(client: TestClient, auth_headers) -> None:
    _, h = auth_headers("super_admin")
    assert client.post(USERS, headers=h, json=new_user(role="owner")).status_code == 422
    r = client.post(USERS, headers=h, json=new_user(password="12345678"))
    assert r.status_code == 422


# --- List / search / paginate ----------------------------------------------------


def test_list_search_filter_and_paginate(client: TestClient, auth_headers, make_user) -> None:
    _, h = auth_headers("super_admin", username="boss")
    for i in range(25):
        make_user("cashier", username=f"till{i:02d}")
    make_user("inventory_officer", username="stockist")

    page = client.get(USERS, headers=h, params={"page": 2, "page_size": 10}).json()
    assert page["total"] == 27 and page["pages"] == 3 and len(page["items"]) == 10

    r = client.get(USERS, headers=h, params={"role": "inventory_officer"}).json()
    assert [u["username"] for u in r["items"]] == ["stockist"]

    r = client.get(USERS, headers=h, params={"search": "TILL1"}).json()
    assert r["total"] == 10

    assert client.get(USERS, headers=h, params={"page_size": 500}).status_code == 422


# --- Update / safety rules -----------------------------------------------------------


def test_update_user_and_audit_diff(client: TestClient, auth_headers, make_user, db) -> None:
    admin, h = auth_headers("super_admin")
    target = make_user("cashier", username="promote")
    r = client.patch(
        f"{USERS}/{target.id}", headers=h, json={"role": "store_manager", "phone": "0722 000 111"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"]["name"] == "store_manager"
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "user.update"))
    assert entry.before == {"role": "cashier", "phone": None}
    assert entry.after == {"role": "store_manager", "phone": "0722 000 111"}
    assert entry.user_id == admin.id


def test_cannot_deactivate_self_or_change_own_role(client: TestClient, auth_headers) -> None:
    admin, h = auth_headers("super_admin")
    assert (
        client.patch(f"{USERS}/{admin.id}", headers=h, json={"is_active": False}).status_code == 422
    )
    assert (
        client.patch(f"{USERS}/{admin.id}", headers=h, json={"role": "cashier"}).status_code == 422
    )


def test_admin_can_demote_another_admin(client: TestClient, auth_headers, make_user) -> None:
    _, h = auth_headers("super_admin", username="admin1")
    other_admin = make_user("super_admin", username="admin2")
    assert (
        client.patch(
            f"{USERS}/{other_admin.id}", headers=h, json={"role": "store_manager"}
        ).status_code
        == 200
    )


def test_deactivation_signs_user_out_immediately(
    client: TestClient, auth_headers, make_user
) -> None:
    _, admin_h = auth_headers("super_admin")
    target = make_user("cashier", username="leaver")
    leaver_h = login(client, "leaver")
    assert (
        client.patch(f"{USERS}/{target.id}", headers=admin_h, json={"is_active": False}).status_code
        == 200
    )
    r = client.get("/api/v1/auth/me", headers=leaver_h)
    assert r.status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "leaver", "password": PASSWORD}
        ).status_code
        == 401
    )


def test_admin_reset_link_unlocks_and_revokes(client: TestClient, auth_headers, make_user) -> None:
    _, admin_h = auth_headers("super_admin")
    target = make_user("cashier", username="forgot")
    old_h = login(client, "forgot")
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"username": "forgot", "password": "bad-Pass-1"})

    r = client.post(f"{USERS}/{target.id}/reset-password", headers=admin_h)
    assert r.status_code == 200
    token = token_from(r.json()["reset_url"])

    # Issuing a second link invalidates the first.
    r2 = client.post(f"{USERS}/{target.id}/reset-password", headers=admin_h)
    stale = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "Fresh-Start-11"}
    )
    assert stale.status_code == 422
    token = token_from(r2.json()["reset_url"])

    ok = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "Fresh-Start-11"}
    )
    assert ok.status_code == 200
    assert client.get("/api/v1/auth/me", headers=old_h).status_code == 401
    login(client, "forgot", "Fresh-Start-11")  # lock cleared


def test_unlock_and_force_sign_out(client: TestClient, auth_headers, make_user, db) -> None:
    _, admin_h = auth_headers("super_admin")
    target = make_user("cashier", username="stuck")
    victim_h = login(client, "stuck")
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"username": "stuck", "password": "bad-Pass-1"})
    listed = client.get(f"{USERS}/{target.id}", headers=admin_h).json()
    assert listed["is_locked"] is True

    assert client.post(f"{USERS}/{target.id}/unlock", headers=admin_h).json()["is_locked"] is False
    login(client, "stuck")

    r = client.post(f"{USERS}/{target.id}/revoke-sessions", headers=admin_h)
    assert r.status_code == 200 and r.json()["message"].startswith("2 session")
    assert client.get("/api/v1/auth/me", headers=victim_h).status_code == 401


def test_get_unknown_user_404(client: TestClient, auth_headers) -> None:
    _, h = auth_headers("super_admin")
    r = client.get(f"{USERS}/99999", headers=h)
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_user_responses_never_contain_password_hash(client: TestClient, auth_headers, db) -> None:
    _, h = auth_headers("super_admin")
    client.post(USERS, headers=h, json=new_user())
    text = client.get(USERS, headers=h).text
    assert "password_hash" not in text and "$argon2" not in text
    user = db.scalar(select(User).where(User.username == "gnjeri"))
    assert user.password_hash.startswith("$argon2id$")

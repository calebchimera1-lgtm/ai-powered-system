"""Regression tests for the security audit fixes: configuration, cookies, rate limits."""

from fastapi.testclient import TestClient

from app.core.config import Settings, production_config_problems
from app.main import app
from tests.conftest import PASSWORD

STRONG_SECRET = "x" * 20 + "Q7v9-k2LmZ3pW8sT1yB4nR6"  # 43 chars, not a placeholder
STRONG_DB = "postgresql+psycopg://inventory:Vq8rT2mW9xK4pL7z@db:5432/inventory"


def settings(**kw) -> Settings:
    base = {"environment": "production", "jwt_secret": STRONG_SECRET, "database_url": STRONG_DB}
    return Settings(**{**base, **kw})


# --- Production configuration fails closed ----------------------------------------------


def test_strong_production_config_has_no_problems() -> None:
    assert production_config_problems(settings()) == []


def test_placeholder_or_short_jwt_secret_is_rejected() -> None:
    for secret in ("change-me-in-env", "CHANGE_ME_generate_a_long_random_value", "s" * 20):
        problems = production_config_problems(settings(jwt_secret=secret))
        assert any("JWT_SECRET" in p for p in problems), secret


def test_default_or_placeholder_db_password_is_rejected() -> None:
    for pw in ("inventory", "CHANGE_ME_db_password", "short"):
        url = f"postgresql+psycopg://inventory:{pw}@db:5432/inventory"
        problems = production_config_problems(settings(database_url=url))
        assert any("POSTGRES_PASSWORD" in p for p in problems), pw


def test_problem_messages_never_contain_the_secret_values() -> None:
    weak = "change-me-but-with-a-long-unique-tail-12345"
    problems = production_config_problems(settings(jwt_secret=weak))
    assert problems and all(weak not in p for p in problems)


def test_api_docs_off_in_production_unless_explicitly_enabled() -> None:
    assert settings().api_docs_enabled is False
    assert settings(expose_api_docs=True).api_docs_enabled is True
    assert settings(environment="development").api_docs_enabled is True


# --- Refresh cookie ------------------------------------------------------------------------


def test_refresh_cookie_is_secure_httponly_strict_over_https(make_user) -> None:
    make_user("cashier", username="cookie_https")
    with TestClient(app, base_url="https://testserver") as https:
        r = https.post(
            "/api/v1/auth/login", json={"username": "cookie_https", "password": PASSWORD}
        )
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "secure" in cookie
    assert "path=/api/v1/auth" in cookie


def test_refresh_cookie_not_marked_secure_over_plain_http(client: TestClient, make_user) -> None:
    # Over plain HTTP a Secure cookie would never come back, so sign-in must still work.
    make_user("cashier", username="cookie_http")
    r = client.post("/api/v1/auth/login", json={"username": "cookie_http", "password": PASSWORD})
    assert r.status_code == 200 and "secure" not in r.headers["set-cookie"].lower()


# --- Rate limits ---------------------------------------------------------------------------


def test_change_password_attempts_are_limited_per_user(client: TestClient, auth_headers) -> None:
    _, h = auth_headers("cashier")
    body = {"current_password": "wrong-guess-1", "new_password": "Another-Pass-77"}
    codes = [
        client.post("/api/v1/auth/change-password", headers=h, json=body).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [422] * 5  # wrong current password
    assert codes[5] == 429  # sixth guess within 15 minutes is refused


def test_backup_creation_is_limited(client: TestClient, auth_headers) -> None:
    _, h = auth_headers("super_admin")
    codes = [client.post("/api/v1/system/backups", headers=h).status_code for _ in range(4)]
    assert codes[3] == 429 and 429 not in codes[:3]


def test_forecast_runs_are_limited(client: TestClient, auth_headers) -> None:
    _, h = auth_headers("store_manager")
    codes = [client.post("/api/v1/forecasts/run", headers=h).status_code for _ in range(6)]
    assert codes[5] == 429 and 429 not in codes[:5]


def test_rate_limited_response_uses_the_standard_error_shape(
    client: TestClient, auth_headers
) -> None:
    _, h = auth_headers("store_manager")
    for _ in range(5):
        client.post("/api/v1/anomalies/scan", headers=h)
    r = client.post("/api/v1/anomalies/scan", headers=h)
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"

"""Test fixtures.

Tests run against a real PostgreSQL database (default `inventory_test`) so constraints,
row locking and JSONB behave exactly as in production. The database is recreated and
migrated with Alembic once per test session, then tables are truncated between tests.
"""

import os
from collections.abc import Iterator

# Configure the app for testing before anything imports app.core.config.
os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+psycopg://inventory:inventory@localhost:5432/inventory_test"
)
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["ENVIRONMENT"] = "test"
os.environ["JWT_SECRET"] = "test-secret-key-for-unit-tests-only"
os.environ["FRONTEND_URL"] = "http://frontend.test"
os.environ["STORAGE_DIR"] = __import__("tempfile").mkdtemp(prefix="inventory-test-storage-")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from alembic import command
from alembic.config import Config
from app.core.database import SessionLocal, engine
from app.core.security import hash_password
from app.models import User
from app.services.rbac_service import get_role, sync_roles_and_permissions

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASSWORD = "Str0ng!Passw0rd"
KEEP_TABLES = {"roles", "permissions", "role_permissions", "alembic_version", "expense_categories"}


def _recreate_database(url: str) -> None:
    db_url = make_url(url)
    admin = create_engine(db_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :d AND pid <> pg_backend_pid()"
            ),
            {"d": db_url.database},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_url.database}"'))
        conn.execute(text(f'CREATE DATABASE "{db_url.database}"'))
    admin.dispose()


def alembic_config(url: str) -> Config:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    url = os.environ["DATABASE_URL"]
    _recreate_database(url)
    command.upgrade(alembic_config(url), "head")
    with SessionLocal() as db:
        sync_roles_and_permissions(db)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    yield
    from app.core.rate_limit import reset_all_limiters

    reset_all_limiters()
    with engine.begin() as conn:
        tables = [
            r[0]
            for r in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            if r[0] not in KEEP_TABLES
        ]
        if tables:
            conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_user(db: Session):
    def _make(
        role: str = "cashier",
        username: str | None = None,
        password: str = PASSWORD,
        **kwargs: object,
    ) -> User:
        username = username or f"{role}_{db.query(User).count() + 1}"
        user = User(
            username=username,
            email=f"{username}@test.local",
            full_name=kwargs.pop("full_name", f"Test {username}"),
            role=get_role(db, role),
            password_hash=hash_password(password),
            is_active=kwargs.pop("is_active", True),
            must_change_password=kwargs.pop("must_change_password", False),
            **kwargs,
        )
        db.add(user)
        db.commit()
        return user

    return _make


XHR = {"X-Requested-With": "XMLHttpRequest"}


def login(client: TestClient, username: str, password: str = PASSWORD) -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def auth_headers(client: TestClient, make_user):
    """Create a user with the given role and return (user, headers)."""

    def _auth(role: str = "super_admin", username: str | None = None):
        user = make_user(role, username=username)
        return user, login(client, user.username)

    return _auth


@pytest.fixture
def catalog(db: Session, make_user):
    """Small helper for building products/stock directly through the services."""
    from decimal import Decimal

    from app.models import Category, Product
    from app.services import inventory_service

    actor = make_user("super_admin", username="catalog_admin")

    class Catalog:
        user = actor

        def category(self, name: str = "Groceries") -> Category:
            cat = Category(name=name)
            db.add(cat)
            db.commit()
            return cat

        def product(self, name: str = "White Sugar 2kg", **kw: object) -> Product:
            defaults: dict[str, object] = {
                "sku": f"SKU-{name[:3].upper()}-{db.query(Product).count() + 1}",
                "selling_price": Decimal("230.00"),
                "unit_of_measure": "pcs",
            }
            defaults.update(kw)
            p = Product(name=name, **defaults)
            db.add(p)
            db.commit()
            return p

        def receive(self, product, qty, cost, expiry=None, batch=None, kind="PURCHASE_IN"):
            ms = inventory_service.apply_movement(
                db,
                product_id=product.id,
                quantity=Decimal(str(qty)),
                movement_type=kind,
                user=actor,
                unit_cost=Decimal(str(cost)),
                batch_info=inventory_service.BatchInfo(batch, expiry),
            )
            db.commit()
            db.refresh(product)
            return ms

    return Catalog()

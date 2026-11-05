"""Audit log API, health check, worker queue and migration reversibility."""

import os

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url

from alembic import command
from app.models import BackgroundJob
from app.services import job_service
from app.workers.runner import Worker
from tests.conftest import _recreate_database, alembic_config, login


def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "database": "ok"}
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    r = client.get("/api/v1/does-not-exist")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_audit_log_filters_and_records_ip(client: TestClient, auth_headers, make_user) -> None:
    admin, h = auth_headers("super_admin")
    make_user("cashier", username="clerk")
    login(client, "clerk")
    client.post("/api/v1/auth/login", json={"username": "clerk", "password": "Wrong-pass-1"})

    all_logs = client.get("/api/v1/audit-logs", headers=h).json()
    assert all_logs["total"] >= 3
    newest = all_logs["items"][0]
    assert newest["action"] == "auth.login_failed"
    assert newest["user"]["username"] == "clerk"
    assert newest["ip_address"] == "testclient"

    auth_only = client.get("/api/v1/audit-logs", headers=h, params={"action": "auth"}).json()
    assert {i["action"] for i in auth_only["items"]} <= {"auth.login", "auth.login_failed"}

    mine = client.get("/api/v1/audit-logs", headers=h, params={"user_id": admin.id}).json()
    assert all(i["user"]["id"] == admin.id for i in mine["items"])


def test_worker_processes_jobs_and_retries_failures(db) -> None:
    ok = job_service.enqueue(db, "system.ping", {"echo": "hello"})
    bad = job_service.enqueue(db, "does.not.exist", max_attempts=2)
    db.commit()

    worker = Worker()
    assert worker.run_once() is True
    assert worker.run_once() is True
    assert worker.run_once() is False  # failed job is delayed for retry

    db.expire_all()
    ok = db.get(BackgroundJob, ok.id)
    bad = db.get(BackgroundJob, bad.id)
    assert ok.status == "SUCCEEDED" and ok.result == {"pong": True, "echo": "hello"}
    assert bad.status == "PENDING" and bad.attempts == 1 and "No handler" in bad.error

    db.execute(text("UPDATE background_jobs SET run_after = now() WHERE id = :i"), {"i": bad.id})
    db.commit()
    assert worker.run_once() is True
    db.expire_all()
    assert db.get(BackgroundJob, bad.id).status == "FAILED"


def test_claim_skips_rows_locked_by_another_worker(db) -> None:
    from app.core.database import SessionLocal

    job_service.enqueue(db, "system.ping")
    job_service.enqueue(db, "system.ping")
    db.commit()
    with SessionLocal() as a, SessionLocal() as b:
        ja = job_service.claim_next(a)
        jb = job_service.claim_next(b)  # must not block or return the same row
        assert ja is not None and jb is not None and ja.id != jb.id
        a.rollback()
        b.rollback()


def test_cleanup_job_runs(db) -> None:
    job_service.enqueue(db, "system.cleanup")
    db.commit()
    assert Worker().run_once() is True
    db.expire_all()
    job = db.scalar(select(BackgroundJob))
    assert job.status == "SUCCEEDED" and "sessions_deleted" in job.result


def test_migrations_downgrade_and_upgrade_cleanly() -> None:
    url = make_url(os.environ["DATABASE_URL"]).set(database="inventory_migration_test")
    url_str = url.render_as_string(hide_password=False)
    _recreate_database(url_str)
    cfg = alembic_config(url_str)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    eng = create_engine(url)
    tables = set(inspect(eng).get_table_names())
    eng.dispose()
    assert {
        "users",
        "roles",
        "permissions",
        "role_permissions",
        "user_sessions",
        "password_reset_tokens",
        "audit_logs",
        "background_jobs",
    } <= tables

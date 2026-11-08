"""Backups: creation through the worker, checksums, rotation, permissions and a full restore."""

import hashlib
import json
import os
import shutil
from datetime import UTC, datetime, timedelta

import psycopg
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.services import backup_service
from app.workers.runner import Worker


def run_jobs() -> None:
    worker = Worker()
    while worker.run_once():
        pass


def _admin_url(dbname: str) -> str:
    base = os.environ["DATABASE_URL"].rsplit("/", 1)[0]
    return f"{base}/{dbname}"


def test_backup_restore_round_trip(client: TestClient, auth_headers, catalog) -> None:  # type: ignore[no-untyped-def]
    admin = auth_headers("super_admin", username="boss")[1]
    sugar = catalog.product("White Sugar 2kg")
    catalog.receive(sugar, 25, 180)
    photo = backup_service.backup_root().parent / "products" / "1" / "photo.jpg"
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(b"jpeg-bytes")

    assert client.post("/api/v1/system/backups", headers=admin).status_code == 202
    run_jobs()
    listing = client.get("/api/v1/system/backups", headers=admin).json()
    assert not listing["running"] and listing["last_error"] is None
    [b] = listing["backups"]
    assert b["kind"] == "manual" and b["verified"]
    assert b["row_counts"]["products"] == 1 and b["schema_revision"]

    # Checksums in the manifest match the files, and downloads work.
    folder = backup_service.backup_root() / b["name"]
    for name, info in b["files"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == info["sha256"]
    r = client.get(f"/api/v1/system/backups/{b['name']}/manifest.json", headers=admin)
    assert r.status_code == 200 and json.loads(r.content)["name"] == b["name"]
    assert (
        client.get("/api/v1/system/backups/..%2Fx/manifest.json", headers=admin).status_code == 404
    )

    # Restore into a scratch database and compare.
    scratch = "inventory_restore_check"
    with psycopg.connect(_admin_url("postgres").replace("+psycopg", ""), autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {scratch}")
        conn.execute(f"CREATE DATABASE {scratch}")
    try:
        photo.unlink()
        backup_service.restore(b["name"], _admin_url(scratch), files=True)
        engine = create_engine(_admin_url(scratch))
        with engine.connect() as conn:
            assert conn.execute(text("SELECT name, quantity_on_hand FROM products")).one() == (
                "White Sugar 2kg",
                25,
            )
            assert conn.execute(text("SELECT count(*) FROM stock_movements")).scalar() == 1
        engine.dispose()
        assert photo.read_bytes() == b"jpeg-bytes"  # uploaded files came back too
    finally:
        with psycopg.connect(
            _admin_url("postgres").replace("+psycopg", ""), autocommit=True
        ) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {scratch} WITH (FORCE)")
        shutil.rmtree(backup_service.backup_root(), ignore_errors=True)


def test_restore_refuses_a_damaged_backup(client: TestClient, auth_headers) -> None:  # type: ignore[no-untyped-def]
    admin = auth_headers("super_admin", username="boss")[1]
    client.post("/api/v1/system/backups", headers=admin)
    run_jobs()
    [b] = backup_service.list_backups()
    with (backup_service.backup_root() / b["name"] / "database.dump").open("ab") as f:
        f.write(b"tampered")
    try:
        backup_service.restore(b["name"], _admin_url("does_not_matter"))
        raise AssertionError("should have refused")
    except backup_service.BackupError as exc:
        assert "checksum" in str(exc)
    finally:
        shutil.rmtree(backup_service.backup_root(), ignore_errors=True)


def test_only_super_admin_manages_backups(client: TestClient, auth_headers) -> None:  # type: ignore[no-untyped-def]
    for role in ("store_manager", "inventory_officer", "cashier"):
        h = auth_headers(role, username=f"u_{role}")[1]
        assert client.get("/api/v1/system/backups", headers=h).status_code == 403
        assert client.post("/api/v1/system/backups", headers=h).status_code == 403


def test_rotation_keeps_7_daily_4_weekly_5_manual() -> None:
    root = backup_service.backup_root()
    shutil.rmtree(root, ignore_errors=True)
    start = datetime(2026, 9, 1, 2, 0, tzinfo=UTC)

    def fake(name: str, kind: str, when: datetime) -> None:
        (root / name).mkdir(parents=True)
        (root / name / "manifest.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "kind": kind,
                    "created_at": when.isoformat(),
                    "files": {},
                }
            )
        )

    for d in range(60):  # 60 nightly backups
        when = start + timedelta(days=d)
        fake(f"{when:%Y%m%d}-020000-daily", "daily", when)
    for i in range(8):
        when = start + timedelta(days=i, hours=5)
        fake(f"{when:%Y%m%d}-070000-manual", "manual", when)
    backup_service.rotate()
    left = backup_service.list_backups()
    daily = [b for b in left if b["kind"] == "daily"]
    manual = [b for b in left if b["kind"] == "manual"]
    assert len(manual) == 5
    # 7 most recent days + the newest of 4 ISO weeks (the latest weeks overlap the 7 days).
    newest = start + timedelta(days=59)
    assert all((newest - datetime.fromisoformat(b["created_at"])).days < 28 for b in daily)
    assert 7 <= len(daily) <= 10
    weeks = {datetime.fromisoformat(b["created_at"]).isocalendar()[:2] for b in daily}
    assert len(weeks) >= 4
    shutil.rmtree(root, ignore_errors=True)
